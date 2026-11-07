use ash::vk;

use crate::gpu::threed::{Draw, address, reg};
use crate::gpu::{Gpu, buffer_cache, formats};
use crate::mem::GuestMemory;
use super::Renderer;
use super::submit::Garbage;

pub(super) struct CheckedBinding {
    cp_seen: usize,
    pending_epoch: u64,
    binding: (vk::Buffer, u64),
}

impl Renderer {
    /// Prepare one bounded prefix per instance-rate stream. The bound address
    /// stays at element zero because Vulkan adds firstInstance when fetching.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn instance_vertex_buffers(
        &mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32],
        streams: &[u32], attributes: &[(u32, u32, vk::Format, u32)],
        first_instance: u32, instances: u32, out: &mut Vec<(u32, vk::Buffer, u64)>,
    ) -> Result<(u32, u32), &'static str> {
        const MAX_PREFIX_BYTES: u64 = 256 << 10;
        const BIND_ALIGNMENT: u64 = 16;
        let last = instances.checked_sub(1)
            .and_then(|offset| first_instance.checked_add(offset))
            .ok_or("instance stream index")?;
        let mut budget = MAX_PREFIX_BYTES;
        let mut prefixes = [None; 16];
        for &stream in streams.iter().filter(|&&stream| instanced_stream(regs, stream)) {
            let base = reg::VERTEX_STREAM + 4 * stream as usize;
            if regs[base + 3] > 1 {
                return Err("instance stream divisor");
            }
            let stride = regs[base] & 0xfff;
            if stride == 0 || stride > self.limits.max_vertex_input_binding_stride
                || stream >= self.limits.max_vertex_input_bindings
            {
                return Err("instance stream stride");
            }
            for &(location, binding, _, offset) in attributes {
                if binding != stream {
                    continue;
                }
                let size_code = regs[reg::VERTEX_ATTRIBUTE + location as usize] >> 21 & 0x3f;
                let (extent, alignment) = formats::vertex_attribute_layout(size_code)
                    .ok_or("instance stream attribute")?;
                if location >= self.limits.max_vertex_input_attributes
                    || offset > self.limits.max_vertex_input_attribute_offset
                    || offset % alignment != 0 || stride % alignment != 0
                    || offset + extent > stride
                {
                    return Err("instance stream attribute");
                }
            }
            let size = (u64::from(last) + 1).checked_mul(u64::from(stride))
                .ok_or("instance stream prefix cap")?;
            budget = budget.checked_sub(size).ok_or("instance stream prefix cap")?;
            let va = address(regs, base + 1);
            let limit = address(regs, reg::VERTEX_STREAM_LIMIT + 2 * stream as usize);
            if va.checked_add(size - 1).is_none_or(|end| end > limit) {
                return Err("instance stream limit");
            }
            let (mapping_start, mapping) = gpu.mapping(va).ok_or("instance stream mapping")?;
            let mapping_offset = va - mapping_start;
            if size > mapping.size - mapping_offset {
                return Err("instance stream mapping");
            }
            let cpu = mapping.cpu.checked_add(mapping_offset).ok_or("instance stream mapping")?;
            let cpu_end = cpu.checked_add(size).ok_or("instance stream mapping")?;
            if mem.bytes(cpu, size).is_none() {
                return Err("instance stream mapping");
            }
            if self.pitch_targets.values().any(|&(target, pitch, rows)| {
                target < cpu_end && cpu < target.saturating_add(u64::from(pitch) * u64::from(rows))
            }) {
                return Err("instance stream pending write");
            }
            let ring_offset = if self.pending_pages.overlapping(cpu, size).next().is_some() {
                if crate::env_var!("KIRIKAE_INSTANCE_PENDING_STREAMS").is_none_or(|value| value != "1") {
                    return Err("instance stream pending write");
                }
                // The latest overlapping write must cover the whole prefix in
                // this serial. The existing helper also enforces the graphics
                // write barrier and refuses later partial overlaps.
                Some(self.pending_in_ring(cpu, size, BIND_ALIGNMENT)
                    .ok_or("instance stream pending write")?)
            } else {
                None
            };
            prefixes[stream as usize] = Some((cpu, size, ring_offset));
        }
        let mut uploaded = 0;
        let mut forwarded = 0;
        // This runs after descriptor and index preparation. The remaining
        // buffer allocations can retire earlier batches but cannot flush the
        // current serial and release the forwarded ranges.
        for (stream, prefix) in prefixes.into_iter().enumerate() {
            if let Some((cpu, size, ring_offset)) = prefix {
                let (buffer, offset) = if let Some(offset) = ring_offset {
                    forwarded |= 1 << stream;
                    (self.ring.buffer, offset)
                } else {
                    let pair = self.checked_guest_buffer(mem, cpu, size, BIND_ALIGNMENT, buffer_cache::Kind::Vertex, true)
                        .map_err(|_| "instance stream upload")?
                        .ok_or("instance stream mapping")?;
                    self.stats.vertex_bytes += size;
                    pair
                };
                out.push((stream as u32, buffer, offset));
                uploaded |= 1 << stream;
            }
        }
        Ok((uploaded, forwarded))
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn vertex_buffers(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], streams: &[u32], draw: Draw, range: Option<(u32, u32)>, uploaded: u32, out: &mut Vec<(u32, vk::Buffer, u64)>) -> Result<(), String> {
        for &s in streams {
            if uploaded & (1 << s) != 0 {
                continue;
            }
            if s == 31 {
                let offset = self.ring_copy(&[0u8; 64], 16).ok_or("ring full")?;
                out.push((31, self.ring.buffer, offset));
                continue;
            }
            let base = reg::VERTEX_STREAM + 4 * s as usize;
            if instanced_stream(regs, s) {
                let stride = (regs[base] & 0xfff) as u64;
                let element = (draw.instance / regs[base + 3].max(1)) as u64;
                let va = address(regs, base + 1) + element * stride;
                if let Some(offset) = gpu.translate(va).and_then(|c| self.pending_in_ring(c, stride.max(4), 1)) {
                    out.push((s, self.ring.buffer, offset));
                    continue;
                }
                let offset = self.ring_guest(gpu, mem, va, stride.max(4), 16, false).map_err(|e| format!("instanced vertex stream {s}: {e}"))?;
                out.push((s, self.ring.buffer, offset));
                continue;
            }
            let start = address(regs, base + 1);
            let limit = address(regs, reg::VERTEX_STREAM_LIMIT + 2 * s as usize);
            let size = (limit + 1).saturating_sub(start).min(64 << 20);
            if size == 0 {
                return Err(format!("vertex stream {s} is empty"));
            }
            let (start, size) = match range {
                Some((lo, hi)) => {
                    let stride = (regs[base] & 0xfff) as u64;
                    let from = start + lo as u64 * stride;
                    let end = (start + (hi as u64 + 1) * stride + 64).min(start + size);
                    (from, end.saturating_sub(from).max(16))
                }
                None => (start, size),
            };
            if crate::gpu::trace() {
                let data = gpu.read(mem, start, size.min(32)).unwrap_or_default();
                let floats: Vec<f32> = data.as_chunks::<4>().0.iter().take(8).map(|b| f32::from_le_bytes(*b)).collect();
                eprintln!("gpu: vertex stream {s} at {start:#x} ({size:#x} bytes): {floats:?}");
            }
            let (buffer, offset) = self.guest_buffer(gpu, mem, start, size, 16, buffer_cache::Kind::Vertex).map_err(|e| format!("vertex stream {s}: {e}"))?;
            self.stats.vertex_bytes += size;
            out.push((s, buffer, offset));
        }
        Ok(())
    }

    pub(super) fn vertex_range(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], draw: Draw) -> Option<(u32, u32)> {
        if draw.count == 0 {
            return None;
        }
        let Some(size) = draw.index_size else {
            return Some((draw.first, draw.first + draw.count - 1));
        };
        let va = address(regs, reg::INDEX_BUFFER) + draw.first as u64 * size as u64;
        let len = draw.count as u64 * size as u64;
        let restart = (regs[reg::PRIMITIVE_RESTART] & 1 == 1).then_some(regs[reg::PRIMITIVE_RESTART + 1]);
        if let Some(key) = self.index_checked
            && gpu.translate(va).is_some_and(|cpu| (cpu, len) == (key.0, key.1))
        {
            return self.buffers.index_range(key, restart, |b| vertex_range(b, size, restart));
        }
        vertex_range(gpu.bytes(mem, va, len)?, size, restart)
    }

    pub(super) fn index_buffer(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], draw: Draw, quads: bool) -> Result<Option<(vk::Buffer, u64, vk::IndexType, u32)>, String> {
        self.index_checked = None;
        let triangles = move |indices: Vec<u32>| -> Vec<u8> {
            let indices = if quads { indices.as_chunks::<4>().0.iter().flat_map(|q| [q[0], q[1], q[2], q[0], q[2], q[3]]).collect() } else { indices };
            indices.iter().flat_map(|i| i.to_le_bytes()).collect()
        };
        let count = if quads { draw.count / 4 * 6 } else { draw.count };
        let bytes = match draw.index_size {
            Some(size) => {
                let va = address(regs, reg::INDEX_BUFFER) + draw.first as u64 * size as u64;
                let len = draw.count as u64 * size as u64;
                let source = gpu.bytes(mem, va, len).ok_or("index buffer unreadable")?;
                if crate::gpu::trace() {
                    eprintln!("gpu: indices {:?}", &source[..source.len().min(16)]);
                }
                let widen = move |b: &[u8]| -> Vec<u8> {
                    triangles(match size {
                        1 => b.iter().map(|&b| b as u32).collect(),
                        2 => b.as_chunks::<2>().0.iter().map(|b| u16::from_le_bytes(*b) as u32).collect(),
                        _ => b.as_chunks::<4>().0.iter().map(|b| u32::from_le_bytes(*b)).collect(),
                    })
                };
                if let Some(cpu) = gpu.translate(va)
                    && self.buffer_cache_on
                {
                    let key = (cpu, len, buffer_cache::Kind::Index(size, quads));
                    self.index_checked = Some(key);
                    if let Some((buffer, offset)) = self.cached(cpu, len, key.2, source, widen) {
                        return Ok(Some((buffer, offset, vk::IndexType::UINT32, count)));
                    }
                    return self.ring_indices(widen(source), count);
                }
                widen(source)
            }
            None if quads => triangles((draw.first..draw.first + draw.count).collect()),
            None => return Ok(None),
        };
        self.ring_indices(bytes, count)
    }

    pub(super) fn ring_indices(&mut self, bytes: Vec<u8>, count: u32) -> Result<Option<(vk::Buffer, u64, vk::IndexType, u32)>, String> {
        let offset = self.ring_copy(&bytes, 16).ok_or("ring full")?;
        Ok(Some((self.ring.buffer, offset, vk::IndexType::UINT32, count)))
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn guest_buffer(&mut self, gpu: &Gpu, mem: &GuestMemory, va: u64, size: u64, align: u64, kind: buffer_cache::Kind) -> Result<(vk::Buffer, u64), String> {
        let cpu = gpu.translate(va);
        if let Some(cpu) = cpu
            && let Some(buffer) = self.checked_guest_buffer(mem, cpu, size, align, kind, false)?
        {
            return Ok(buffer);
        }
        if let Some(offset) = cpu.and_then(|c| self.pending_in_ring(c, size, align)) {
            return Ok((self.ring.buffer, offset));
        }
        let offset = self.ring_guest(gpu, mem, va, size, align, kind == buffer_cache::Kind::Constant)?;
        Ok((self.ring.buffer, offset))
    }

    fn checked_guest_buffer(&mut self, mem: &GuestMemory, cpu: u64, size: u64,
        align: u64, kind: buffer_cache::Kind, pending_already_checked: bool) -> Result<Option<(vk::Buffer, u64)>, String> {
        let key = (cpu, size, kind);
        let pending_epoch = self.pending_pages.next;
        let checked = self.checked.get_mut(&key);
        // This proof belongs to the exact translated CPU range and is used
        // under the renderer lock. Publishing a write advances the epoch;
        // retirement only removes pending entries and records the CPU write.
        if !pending_already_checked
            && (kind != buffer_cache::Kind::ReadOnlyStorage || !self.pending_pages.pages.is_empty())
        {
            if self.reuse_pending_checks && checked.as_ref().is_some_and(|entry| entry.pending_epoch == pending_epoch) {
                self.stats.checked_pending_reused += 1;
            } else {
                if self.reuse_pending_checks { self.stats.checked_pending_scans += 1; }
                if self.pending_pages.overlapping(cpu, size).next().is_some() {
                    return Ok(None);
                }
            }
        }
        if crate::env_var!("KIRIKAE_NO_CHECKED").is_none()
            && let Some(entry) = checked
            && !self.cp_writes.since(cpu, size, entry.cp_seen)
        {
            entry.cp_seen = self.cp_writes.len();
            entry.pending_epoch = pending_epoch;
            return Ok(Some(entry.binding));
        }
        let Some(data) = mem.bytes(cpu, size) else { return Ok(None); };
        let resident = self.cached(cpu, size, kind, data, |bytes| bytes.to_vec())
            .filter(|&(_, offset)| kind != buffer_cache::Kind::ReadOnlyStorage || offset.is_multiple_of(align));
        let (buffer, offset) = match resident {
            Some(binding) => binding,
            None => (self.ring.buffer, self.ring_copy(data, align).ok_or("ring full")?),
        };
        self.checked.insert(key, CheckedBinding {
            cp_seen: self.cp_writes.len(), pending_epoch, binding: (buffer, offset),
        });
        Ok(Some((buffer, offset)))
    }

    pub(super) fn readonly_storage_buffer(&mut self, gpu: &Gpu, mem: &GuestMemory,
        va: u64, size: u64, align: u64) -> Result<Option<(vk::Buffer, u64)>, String> {
        // Only single mapped, CPU-readable ranges can enter the resident cache.
        // Pending GPU writes must keep the ordinary shared-ring behavior.
        if va == 0 || size > buffer_cache::ARENA {
            return Ok(None);
        }
        let Some((start, mapping)) = gpu.mapping(va) else { return Ok(None); };
        let offset = va - start;
        if size > mapping.size - offset {
            return Ok(None);
        }
        let cpu = mapping.cpu + offset;
        self.checked_guest_buffer(mem, cpu, size, align, buffer_cache::Kind::ReadOnlyStorage, false)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn cached(&mut self, cpu: u64, size: u64, kind: buffer_cache::Kind, data: &[u8], convert: impl FnOnce(&[u8]) -> Vec<u8>) -> Option<(vk::Buffer, u64)> {
        if !self.buffer_cache_on {
            return None;
        }
        let frame = crate::display::FRAMES.load(std::sync::atomic::Ordering::Relaxed);
        let mut retired = Vec::new();
        let found = self.buffers.lookup(&self.device, (cpu, size, kind), data, frame, convert, &mut retired);
        self.buffers.evict(frame, &mut retired);
        self.garbage.extend(retired.into_iter().map(Garbage::Block));
        self.stats.cached_bytes = self.buffers.hits;
        self.stats.cache_memory = self.buffers.memory();
        found
    }
}

pub(super) fn vertex_range(bytes: &[u8], size: u32, restart: Option<u32>) -> Option<(u32, u32)> {
    let (mut lo, mut hi) = (u32::MAX, 0u32);
    let mut see = |i: u32| {
        if Some(i) != restart {
            lo = lo.min(i);
            hi = hi.max(i);
        }
    };
    match size {
        1 => bytes.iter().for_each(|&b| see(b as u32)),
        2 => bytes.as_chunks::<2>().0.iter().for_each(|b| see(u16::from_le_bytes(*b) as u32)),
        _ => bytes.as_chunks::<4>().0.iter().for_each(|b| see(u32::from_le_bytes(*b))),
    }
    (lo <= hi).then_some((lo, hi))
}

pub(super) fn instanced_stream(regs: &[u32], stream: u32) -> bool {
    stream < 16 && regs[0x620 + stream as usize] & 1 == 1
}
