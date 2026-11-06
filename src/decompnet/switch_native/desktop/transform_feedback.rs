//! Maxwell stream-out for direct, vertex-only point draws.

use ash::vk;
use kirikae_maxwell::{XfbBuffer, XfbLayout};

use crate::gpu::Gpu;
use crate::gpu::threed::{Draw, address, reg, stage_enabled};
use crate::mem::GuestMemory;
use super::Renderer;

const BUFFER_BASE: usize = 0x380 / 4;
const CONTROL_BASE: usize = 0x700 / 4;
const LAYOUT_BASE: usize = 0x2800 / 4;
const BUFFER_COUNT: usize = 4;

pub(super) struct TransformFeedback {
    api: ash::ext::transform_feedback::Device,
    limits: vk::PhysicalDeviceTransformFeedbackPropertiesEXT<'static>,
}

impl TransformFeedback {
    pub(super) fn new(instance: &ash::Instance, device: &ash::Device, physical: vk::PhysicalDevice) -> Self {
        let mut limits = vk::PhysicalDeviceTransformFeedbackPropertiesEXT::default();
        let mut properties = vk::PhysicalDeviceProperties2::default().push_next(&mut limits);
        unsafe { instance.get_physical_device_properties2(physical, &mut properties) };
        Self { api: ash::ext::transform_feedback::Device::new(instance, device), limits }
    }
}

#[derive(Clone, Copy, Debug)]
struct CaptureTarget {
    cpu: u64,
    bytes: u64,
    relative: u64,
}

pub(super) struct Capture {
    pub(super) layout: XfbLayout,
    targets: [Option<CaptureTarget>; BUFFER_COUNT],
    bytes: u64,
}

impl Renderer {
    pub(super) fn stream_capture(&self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], draw: Draw,
        cursors: &[u64; BUFFER_COUNT]) -> Result<Option<Capture>, String> {
        if regs[reg::STREAM_OUTPUT] & 1 == 0 || draw.count == 0 {
            return Ok(None);
        }
        if regs[reg::RASTER_ENABLE] & 1 != 0
            || draw.topology != 0 || draw.index_size.is_some() || draw.instance != 0
            || [0, 2, 3, 4, 5].into_iter().any(|stage| stage_enabled(regs, stage))
            || (regs[0x54e] & 1 == 1 && (regs[0x4b3] & 1 == 1 || regs[0x4ba] & 1 == 1 || regs[0x4e0] & 1 == 1))
        {
            return Err("transform feedback requires vertex-only direct point draws with rasterization disabled".into());
        }
        let mut capture = Capture { layout: std::array::from_fn(|_| None), targets: [None; BUFFER_COUNT], bytes: 0 };
        let mut stream_stride = 0;
        for (slot, &cursor) in cursors.iter().enumerate() {
            let base = BUFFER_BASE + slot * 8;
            let control = CONTROL_BASE + slot * 4;
            let count = (regs[control + 1] & 0xff) as usize;
            if regs[base] & 1 == 0 || count == 0 {
                continue;
            }
            let feature = self.transform_feedback.as_ref().ok_or("Vulkan transform feedback unavailable")?;
            let stride = regs[control + 2];
            if slot >= feature.limits.max_transform_feedback_buffers as usize
                || regs[control] & 3 != 0 || count > 128 || stride != count as u32 * 4
                || stride > feature.limits.max_transform_feedback_buffer_data_stride
                || stride > feature.limits.max_transform_feedback_buffer_data_size
            {
                return Err(format!("unsupported transform feedback layout for buffer {slot}"));
            }
            stream_stride += stride;
            if stream_stride > feature.limits.max_transform_feedback_stream_data_size {
                return Err("transform feedback stream exceeds Vulkan data size".into());
            }
            let bytes = u64::from(draw.count) * u64::from(stride);
            let limit = u64::from(regs[base + 3]);
            if cursor % 4 != 0 || cursor.checked_add(bytes).is_none_or(|end| end > limit)
                || bytes > feature.limits.max_transform_feedback_buffer_size
            {
                return Err(format!("transform feedback buffer {slot} out of bounds: cursor {cursor:#x}, bytes {bytes:#x}, limit {limit:#x}"));
            }
            let va = address(regs, base + 1).checked_add(cursor).ok_or("transform feedback address overflow")?;
            let pieces = gpu.pieces(va, bytes).ok_or("transform feedback buffer is unmapped")?;
            let &[(cpu, size)] = pieces.as_slice() else { return Err("non-contiguous transform feedback buffer".into()) };
            if size != bytes || mem.bytes(cpu, size).is_none() {
                return Err("invalid transform feedback guest range".into());
            }
            if capture.targets.iter().flatten().any(|other| cpu < other.cpu + other.bytes && other.cpu < cpu + size) {
                return Err("overlapping transform feedback buffers".into());
            }
            let layout = LAYOUT_BASE + slot * 32;
            let attributes = (0..count).map(|i| (regs[layout + i / 4] >> ((i % 4) * 8)) as u8).collect();
            capture.layout[slot] = Some(XfbBuffer { stride, attributes });
            capture.targets[slot] = Some(CaptureTarget { cpu, bytes, relative: capture.bytes });
            capture.bytes += bytes;
        }
        Ok((capture.bytes != 0).then_some(capture))
    }

    pub(super) fn resolve_stream_overlap(&mut self, capture: &Capture) {
        // A guest may reload its cursor before a batch is submitted. Finish the
        // previous write so ring_guest never copies overlapping destination regions.
        for target in capture.targets.iter().flatten() {
            if self.pending_pages.overlapping(target.cpu, target.bytes).any(|(_, p)| p.2 == self.serial) {
                self.resolve(target.cpu, target.bytes);
            }
        }
    }

    pub(super) fn reserve_stream_capture(&mut self, capture: &Capture) -> Result<u64, String> {
        self.ring_alloc(capture.bytes, 16).map(|(offset, _)| offset).ok_or_else(|| "transform feedback ring is full".into())
    }

    pub(super) fn begin_stream_capture(&self, capture: &Capture, offset: u64) {
        let fp = self.transform_feedback.as_ref().expect("validated transform feedback feature").api.fp();
        unsafe {
            for (slot, target) in capture.targets.iter().enumerate() {
                if let Some(target) = target {
                    (fp.cmd_bind_transform_feedback_buffers_ext)(self.cmd, slot as u32, 1, &self.ring.buffer,
                        &(offset + target.relative), &target.bytes);
                }
            }
            (fp.cmd_begin_transform_feedback_ext)(self.cmd, 0, 0, std::ptr::null(), std::ptr::null());
        }
    }

    pub(super) fn end_stream_capture(&mut self, capture: &Capture, offset: u64, cursors: &mut [u64; BUFFER_COUNT]) {
        let fp = self.transform_feedback.as_ref().expect("validated transform feedback feature").api.fp();
        unsafe { (fp.cmd_end_transform_feedback_ext)(self.cmd, 0, 0, std::ptr::null(), std::ptr::null()) };
        // End the rendering instance before making captured bytes visible to
        // later vertex input, buffer copies and batch writeback.
        self.end_rendering();
        let memory = [vk::MemoryBarrier::default()
            .src_access_mask(vk::AccessFlags::TRANSFORM_FEEDBACK_WRITE_EXT)
            .dst_access_mask(vk::AccessFlags::MEMORY_READ | vk::AccessFlags::MEMORY_WRITE | vk::AccessFlags::HOST_READ)];
        unsafe {
            self.device.cmd_pipeline_barrier(self.cmd,
                vk::PipelineStageFlags::TRANSFORM_FEEDBACK_EXT,
                vk::PipelineStageFlags::ALL_COMMANDS | vk::PipelineStageFlags::HOST,
                vk::DependencyFlags::empty(), &memory, &[], &[]);
        }
        for (cursor, target) in cursors.iter_mut().zip(&capture.targets) {
            if let Some(target) = target {
                let ring_offset = offset + target.relative;
                self.write_back.push((target.cpu, ring_offset, target.bytes));
                self.pending.push((target.cpu, target.bytes, self.serial, ring_offset));
                self.pending_pages.add((target.cpu, target.bytes, self.serial, ring_offset));
                *cursor += target.bytes;
                if crate::gpu::trace() {
                    eprintln!("gpu: transform feedback {:#x} + {:#x} bytes", target.cpu, target.bytes);
                }
            }
        }
        self.pending_flag.store(true, std::sync::atomic::Ordering::Relaxed);
    }
}
