use std::path::PathBuf;

use ash::vk;

use super::Renderer;
use super::images::{ImageKey, aspect_of};
use super::present_filter::{self, PresentFilter};
use super::readback::decode_pixels;

pub(super) struct Swapchain {
    pub(super) surface: vk::SurfaceKHR,
    pub(super) handle: vk::SwapchainKHR,
    pub(super) images: Vec<vk::Image>,
    pub(super) extent: vk::Extent2D,
    pub(super) srgb: bool,
    pub(super) done: Vec<vk::Semaphore>,
    pub(super) stale: bool,
    pub(super) format: vk::Format,
    pub(super) readable: bool,
    pub(super) filter: Option<PresentFilter>,
}

pub(super) struct PresentDump {
    directory: PathBuf,
    first: u64,
    count: u64,
    presented: u64,
}

impl PresentDump {
    pub(super) fn from_env() -> Option<Self> {
        let directory = crate::env_var!("KIRIKAE_PRESENT_DUMP")?.into();
        let first = crate::env_var!("KIRIKAE_PRESENT_DUMP_FROM").and_then(|v| v.to_str()?.parse::<u64>().ok()).unwrap_or(1).max(1);
        let count = crate::env_var!("KIRIKAE_PRESENT_DUMP_COUNT").and_then(|v| v.to_str()?.parse::<u64>().ok()).unwrap_or(u64::MAX);
        (count > 0).then_some(Self { directory, first, count, presented: 0 })
    }

    fn due(&self) -> bool {
        self.presented.saturating_add(1).checked_sub(self.first)
            .is_some_and(|offset| offset.is_multiple_of(60) && offset / 60 < self.count)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Presented {
    Shown,
    NoImage,
    NoSwapchain,
}

pub(super) const PRESENT: u64 = 1 << 60;

impl Renderer {
    pub fn present(&mut self, cpu: u64, width: u32, height: u32, flip_h: bool, flip_v: bool) -> Presented {
        if self.swapchain_fn.is_none() || self.present_failed {
            return Presented::NoSwapchain;
        }
        let Some(key) = self.find_image(cpu, width, height, vk::Format::R8G8B8A8_UNORM).filter(|k| self.images[k].gpu_dirty && aspect_of(k.format) == vk::ImageAspectFlags::COLOR) else {
            return Presented::NoImage;
        };
        self.present_image(key, width, height, flip_h, flip_v)
    }

    pub fn present_pixels(&mut self, width: u32, height: u32, pixels: &[u32]) -> Presented {
        if self.swapchain_fn.is_none() || self.present_failed || pixels.len() != (width * height) as usize {
            return Presented::NoSwapchain;
        }
        let key = ImageKey { cpu: PRESENT, format: vk::Format::B8G8R8A8_UNORM, width, height };
        if !self.images.contains_key(&key) {
            let old: Vec<ImageKey> = self.images.keys().copied().filter(|k| k.cpu == PRESENT).collect();
            for k in old {
                self.destroy_image(k);
            }
            if self.create_image(key, 1, 1).is_err() {
                return Presented::NoSwapchain;
            }
        }
        let bytes: Vec<u8> = pixels.iter().flat_map(|p| p.to_le_bytes()).collect();
        self.upload(key, &[(width, height, bytes)]);
        self.present_image(key, width, height, false, false)
    }

    pub(super) fn present_image(&mut self, key: ImageKey, width: u32, height: u32, flip_h: bool, flip_v: bool) -> Presented {
        let srgb = matches!(key.format, vk::Format::R8G8B8A8_SRGB | vk::Format::B8G8R8A8_SRGB | vk::Format::A8B8G8R8_SRGB_PACK32);
        let dump = self.present_dump.as_ref().filter(|dump| dump.due()).map(|dump| dump.directory.clone());
        // The readback allocator may flush the command buffer and advance the
        // batch. Allocate before acquiring the image with that batch's semaphore.
        let readback = if dump.is_some() && self.prepare_swapchain(srgb).is_some() {
            let sc = self.swapchain.as_ref().unwrap();
            let extent = sc.extent;
            sc.readable.then_some(extent).and_then(|extent| {
                self.readback_buffer(extent.width as u64 * extent.height as u64 * 4).map(|(buffer, _)| (buffer, extent))
            })
        } else {
            None
        };
        let Some(index) = self.acquire(srgb) else {
            return if self.swapchain.is_some() { Presented::Shown } else { Presented::NoSwapchain };
        };
        let index = index as usize;
        let sc = self.swapchain.as_ref().unwrap();
        let (target, extent, done) = (sc.images[index], sc.extent, sc.done[index]);
        let readback = readback.filter(|(_, prepared)| sc.readable && *prepared == extent).map(|(buffer, _)| buffer);
        let visible = [width.min(key.width), height.min(key.height)];
        let cubic = if self.present_filter_cubic && sc.filter.is_some()
            && let Some(transform) = present_filter::transform(key, [0, 0, visible[0], visible[1]], extent, [flip_h, flip_v])
        {
            match self.present_filter_source_view(key) {
                Ok(view) => Some((view, transform)),
                Err(error) => {
                    eprintln!("kirikae: cannot sample the presentation image ({error:?}); using linear presentation");
                    self.present_filter_cubic = false;
                    None
                }
            }
        } else {
            None
        };
        self.begin();
        self.end_rendering();
        self.barrier();
        let (write_layout, write_stage, write_access) = if cubic.is_some() {
            (vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL, vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT, vk::AccessFlags::COLOR_ATTACHMENT_WRITE)
        } else {
            (vk::ImageLayout::TRANSFER_DST_OPTIMAL, vk::PipelineStageFlags::TRANSFER, vk::AccessFlags::TRANSFER_WRITE)
        };
        let range = vk::ImageSubresourceRange { aspect_mask: vk::ImageAspectFlags::COLOR, base_mip_level: 0, level_count: 1, base_array_layer: 0, layer_count: 1 };
        let to_write = [vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::UNDEFINED)
            .new_layout(write_layout)
            .dst_access_mask(write_access)
            .image(target)
            .subresource_range(range)];
        let sub = vk::ImageSubresourceLayers { aspect_mask: vk::ImageAspectFlags::COLOR, mip_level: 0, base_array_layer: 0, layer_count: 1 };
        unsafe {
            let d = &self.device;
            d.cmd_pipeline_barrier(self.cmd, write_stage, write_stage, vk::DependencyFlags::empty(), &[], &[], &to_write);
            if let Some((view, transform)) = cubic {
                let filter = self.swapchain.as_mut().unwrap().filter.as_mut().unwrap();
                filter.record(self.push.as_ref().unwrap(), self.cmd, index, extent, view, visible, transform);
            } else {
                let [w, h] = visible.map(|v| v as i32);
                let (x0, x1) = if flip_h { (extent.width as i32, 0) } else { (0, extent.width as i32) };
                let (y0, y1) = if flip_v { (extent.height as i32, 0) } else { (0, extent.height as i32) };
                let region = [vk::ImageBlit::default()
                    .src_subresource(sub)
                    .src_offsets([vk::Offset3D { x: 0, y: 0, z: 0 }, vk::Offset3D { x: w, y: h, z: 1 }])
                    .dst_subresource(sub)
                    .dst_offsets([vk::Offset3D { x: x0, y: y0, z: 0 }, vk::Offset3D { x: x1, y: y1, z: 1 }])];
                d.cmd_blit_image(self.cmd, self.images[&key].image, vk::ImageLayout::GENERAL, target, write_layout, &region, vk::Filter::LINEAR);
            }
            let (last_layout, last_stage, last_access) = if let Some(buffer) = readback {
                let to_src = [vk::ImageMemoryBarrier::default()
                    .old_layout(write_layout)
                    .new_layout(vk::ImageLayout::TRANSFER_SRC_OPTIMAL)
                    .src_access_mask(write_access)
                    .dst_access_mask(vk::AccessFlags::TRANSFER_READ)
                    .image(target)
                    .subresource_range(range)];
                d.cmd_pipeline_barrier(self.cmd, write_stage, vk::PipelineStageFlags::TRANSFER, vk::DependencyFlags::empty(), &[], &[], &to_src);
                let copy = [vk::BufferImageCopy::default().image_subresource(sub).image_extent(vk::Extent3D { width: extent.width, height: extent.height, depth: 1 })];
                d.cmd_copy_image_to_buffer(self.cmd, target, vk::ImageLayout::TRANSFER_SRC_OPTIMAL, buffer, &copy);
                (vk::ImageLayout::TRANSFER_SRC_OPTIMAL, vk::PipelineStageFlags::TRANSFER, vk::AccessFlags::TRANSFER_READ)
            } else {
                (write_layout, write_stage, write_access)
            };
            let to_present = [vk::ImageMemoryBarrier::default()
                .old_layout(last_layout)
                .new_layout(vk::ImageLayout::PRESENT_SRC_KHR)
                .src_access_mask(last_access)
                .image(target)
                .subresource_range(range)];
            d.cmd_pipeline_barrier(self.cmd, last_stage, vk::PipelineStageFlags::BOTTOM_OF_PIPE, vk::DependencyFlags::empty(), &[], &[], &to_present);
        }
        self.submit_wait = Some((self.batches[self.current].acquired, write_stage));
        self.submit_signal = Some(done);
        self.flush();
        let sc = self.swapchain.as_mut().unwrap();
        let (waits, swapchains, indices) = ([done], [sc.handle], [index as u32]);
        let info = vk::PresentInfoKHR::default().wait_semaphores(&waits).swapchains(&swapchains).image_indices(&indices);
        let presented = match unsafe { self.swapchain_fn.as_ref().unwrap().queue_present(self.queue, &info) } {
            Ok(suboptimal) => {
                sc.stale |= suboptimal;
                true
            }
            Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => {
                sc.stale = true;
                false
            }
            Err(e) => {
                eprintln!("kirikae: presenting failed ({e:?}); the swapchain is made again");
                sc.stale = true;
                false
            }
        };
        let format = sc.format;
        self.stats.presents += 1;
        if presented && let Some(state) = self.present_dump.as_mut() {
            state.presented += 1;
        }
        if presented && let (Some(dir), Some(_)) = (dump, readback) {
            let number = self.present_dump.as_ref().unwrap().presented;
            self.finish();
            if let Some((_, memory, _, ptr)) = self.readback {
                if !self.readback_coherent {
                    let range = [vk::MappedMemoryRange::default().memory(memory).offset(0).size(vk::WHOLE_SIZE)];
                    unsafe { self.device.invalidate_mapped_memory_ranges(&range).ok() };
                }
                let bytes = unsafe { std::slice::from_raw_parts(ptr, (extent.width * extent.height * 4) as usize) };
                if let Some(pixels) = decode_pixels(format, bytes) {
                    let name = format!("present{number:06}.png");
                    let path = dir.join(&name);
                    if crate::display::write_png(&path, extent.width, extent.height, &pixels).is_ok() {
                        let frame = crate::display::FRAMES.load(std::sync::atomic::Ordering::Relaxed) + 1;
                        eprintln!("kirikae: present dump {name} (display frame {frame})");
                    }
                }
            }
        }
        Presented::Shown
    }

    fn present_filter_source_view(&mut self, key: ImageKey) -> Result<vk::ImageView, vk::Result> {
        let image = self.images.get_mut(&key).unwrap();
        let spec = (key.format, [vk::ComponentSwizzle::IDENTITY; 4], vk::ImageViewType::TYPE_2D, 0, 1, 0);
        if let Some(&view) = image.views.get(&spec) {
            return Ok(view);
        }
        let view = present_filter::color_view(&self.device, image.image, key.format)?;
        image.views.insert(spec, view);
        Ok(view)
    }

    pub(super) fn acquire(&mut self, srgb: bool) -> Option<u32> {
        for _ in 0..2 {
            self.prepare_swapchain(srgb)?;
            let sc = self.swapchain.as_mut()?;
            let semaphore = self.batches[self.current].acquired;
            match unsafe { self.swapchain_fn.as_ref()?.acquire_next_image(sc.handle, 100_000_000, semaphore, vk::Fence::null()) } {
                Ok((index, suboptimal)) => {
                    sc.stale |= suboptimal;
                    return Some(index);
                }
                Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => sc.stale = true,
                Err(vk::Result::ERROR_SURFACE_LOST_KHR) => {
                    self.drop_swapchain(true);
                }
                Err(_) => return None,
            }
        }
        None
    }

    pub(super) fn prepare_swapchain(&mut self, srgb: bool) -> Option<()> {
        let surface_fn = self.surface_fn.clone()?;
        let surface = match &self.swapchain {
            Some(sc) => sc.surface,
            None => {
                let surface = self.create_surface()?;
                let supported = unsafe { surface_fn.get_physical_device_surface_support(self.physical, self.family, surface) }.unwrap_or(false);
                if !supported {
                    eprintln!("kirikae: the graphics queue cannot present to the window; frames are read back instead");
                    unsafe { surface_fn.destroy_surface(surface, None) };
                    self.present_failed = true;
                    return None;
                }
                self.swapchain = Some(Swapchain {
                    surface,
                    handle: vk::SwapchainKHR::null(),
                    images: Vec::new(),
                    extent: vk::Extent2D::default(),
                    srgb,
                    done: Vec::new(),
                    stale: true,
                    format: vk::Format::UNDEFINED,
                    readable: false,
                    filter: None,
                });
                surface
            }
        };
        let caps = unsafe { surface_fn.get_physical_device_surface_capabilities(self.physical, surface) }.ok()?;
        let mut extent = caps.current_extent;
        if extent.width == u32::MAX {
            let (w, h) = crate::display::window_size()?;
            extent = vk::Extent2D {
                width: w.clamp(caps.min_image_extent.width, caps.max_image_extent.width),
                height: h.clamp(caps.min_image_extent.height, caps.max_image_extent.height),
            };
        }
        if extent.width == 0 || extent.height == 0 {
            return None;
        }
        let sc = self.swapchain.as_ref()?;
        if !sc.stale && sc.extent == extent && sc.srgb == srgb {
            return Some(());
        }
        if !caps.supported_usage_flags.contains(vk::ImageUsageFlags::TRANSFER_DST) {
            eprintln!("kirikae: the window's swapchain cannot be blitted to; frames are read back instead");
            self.drop_swapchain(true);
            self.present_failed = true;
            return None;
        }
        self.finish();
        unsafe { self.device.device_wait_idle().ok()? };
        let formats = unsafe { surface_fn.get_physical_device_surface_formats(self.physical, surface) }.ok()?;
        let wanted: &[vk::Format] = if srgb { &[vk::Format::B8G8R8A8_SRGB, vk::Format::R8G8B8A8_SRGB] } else { &[vk::Format::B8G8R8A8_UNORM, vk::Format::R8G8B8A8_UNORM] };
        let blit_dst = |f: vk::Format| unsafe { self.instance.get_physical_device_format_properties(self.physical, f) }.optimal_tiling_features.contains(vk::FormatFeatureFlags::BLIT_DST);
        let format = wanted
            .iter()
            .find_map(|w| formats.iter().find(|f| f.format == *w))
            .or_else(|| formats.iter().find(|f| blit_dst(f.format)))
            .copied()?;
        let modes = unsafe { surface_fn.get_physical_device_surface_present_modes(self.physical, surface) }.unwrap_or_default();
        let order: &[vk::PresentModeKHR] =
            if crate::env_var!("KIRIKAE_VSYNC").is_some() { &[vk::PresentModeKHR::FIFO] } else { &[vk::PresentModeKHR::MAILBOX, vk::PresentModeKHR::IMMEDIATE, vk::PresentModeKHR::FIFO] };
        let mode = order.iter().copied().find(|m| modes.contains(m)).unwrap_or(vk::PresentModeKHR::FIFO);
        let count = if caps.max_image_count > 0 { (caps.min_image_count + 1).min(caps.max_image_count) } else { caps.min_image_count + 1 };
        let old = self.swapchain.as_ref().map_or(vk::SwapchainKHR::null(), |sc| sc.handle);
        let readable = self.present_dump.is_some() && caps.supported_usage_flags.contains(vk::ImageUsageFlags::TRANSFER_SRC);
        let usage = if readable { vk::ImageUsageFlags::TRANSFER_DST | vk::ImageUsageFlags::TRANSFER_SRC } else { vk::ImageUsageFlags::TRANSFER_DST };
        let mut filter = self.present_filter_cubic && self.push.is_some() && present_filter::rgba8(format.format)
            && caps.supported_usage_flags.contains(vk::ImageUsageFlags::COLOR_ATTACHMENT)
            && unsafe { self.instance.get_physical_device_format_properties(self.physical, format.format) }
                .optimal_tiling_features.contains(vk::FormatFeatureFlags::COLOR_ATTACHMENT);
        let filter_usage = if filter { vk::ImageUsageFlags::COLOR_ATTACHMENT } else { vk::ImageUsageFlags::empty() };
        let info = vk::SwapchainCreateInfoKHR::default()
            .surface(surface)
            .min_image_count(count)
            .image_format(format.format)
            .image_color_space(format.color_space)
            .image_extent(extent)
            .image_array_layers(1)
            .image_usage(usage | filter_usage)
            .image_sharing_mode(vk::SharingMode::EXCLUSIVE)
            .pre_transform(caps.current_transform)
            .composite_alpha(vk::CompositeAlphaFlagsKHR::OPAQUE)
            .present_mode(mode)
            .clipped(true)
            .old_swapchain(old);
        let swapchain_fn = self.swapchain_fn.clone()?;
        let made = unsafe { swapchain_fn.create_swapchain(&info, None) }.or_else(|error| {
            if !filter {
                return Err(error);
            }
            eprintln!("kirikae: cannot make a color-attachment swapchain ({error:?}); using linear presentation");
            // A failed replacement still retires oldSwapchain. Release that
            // handle before retrying with only the ordinary transfer usage.
            self.drop_swapchain(false);
            filter = false;
            let info = info.image_usage(usage).old_swapchain(vk::SwapchainKHR::null());
            unsafe { swapchain_fn.create_swapchain(&info, None) }
        });
        let handle = match made {
            Ok(h) => h,
            Err(e) => {
                eprintln!("kirikae: cannot make the window's swapchain ({e:?}); frames are read back instead");
                self.drop_swapchain(true);
                self.present_failed = true;
                return None;
            }
        };
        self.drop_swapchain(false);
        let images = match unsafe { swapchain_fn.get_swapchain_images(handle) } {
            Ok(images) => images,
            Err(error) => {
                eprintln!("kirikae: cannot enumerate the window's swapchain ({error:?}); frames are read back instead");
                unsafe { swapchain_fn.destroy_swapchain(handle, None) };
                self.drop_swapchain(true);
                self.present_failed = true;
                return None;
            }
        };
        let done = images.iter().map(|_| unsafe { self.device.create_semaphore(&vk::SemaphoreCreateInfo::default(), None).unwrap() }).collect();
        let filter = if filter {
            match PresentFilter::new(&self.device, format.format, &images) {
                Ok(filter) => Some(filter),
                Err(error) => {
                    eprintln!("kirikae: cannot prepare the cubic presentation filter ({error:?}); using linear presentation");
                    None
                }
            }
        } else {
            None
        };
        let sc = self.swapchain.as_mut()?;
        *sc = Swapchain { surface, handle, images, extent, srgb, done, stale: false, format: format.format, readable, filter };
        if let Some(set_mode) = self.nv_swapchain_boost {
            // The boost hint works independently of the swapchain's latency mode.
            let boost = vk::LatencySleepModeInfoNV::default().low_latency_mode(false).low_latency_boost(true).minimum_interval_us(0);
            let result = unsafe { set_mode(self.device.handle(), handle, &boost) };
            if result == vk::Result::SUCCESS {
                eprintln!("kirikae: requested NVIDIA swapchain boost ({}x{})", extent.width, extent.height);
            } else {
                eprintln!("kirikae: NVIDIA swapchain boost request failed ({result:?}); using ordinary presentation");
                self.nv_swapchain_boost = None;
            }
        }
        if crate::gpu::trace() || self.stats.presents == 0 {
            eprintln!("kirikae: presenting to the window through a swapchain ({}x{}, {:?}, {mode:?})", extent.width, extent.height, format.format);
        }
        Some(())
    }

    pub(super) fn drop_swapchain(&mut self, surface: bool) {
        let Some(sc) = self.swapchain.as_mut() else { return };
        unsafe {
            let _ = self.device.device_wait_idle();
            drop(sc.filter.take());
            for s in sc.done.drain(..) {
                self.device.destroy_semaphore(s, None);
            }
            if sc.handle != vk::SwapchainKHR::null()
                && let Some(f) = &self.swapchain_fn
            {
                f.destroy_swapchain(sc.handle, None);
            }
            sc.handle = vk::SwapchainKHR::null();
            sc.images.clear();
            sc.stale = true;
        }
        if surface {
            let sc = self.swapchain.take().unwrap();
            if let Some(f) = &self.surface_fn {
                unsafe { f.destroy_surface(sc.surface, None) };
            }
        }
    }

    pub(super) fn create_surface(&mut self) -> Option<vk::SurfaceKHR> {
        use crate::display::WindowHandle as W;
        let handle = crate::display::window_handle()?;
        let needed = match handle {
            W::Win32 { .. } => ash::khr::win32_surface::NAME,
            W::Xlib { .. } => ash::khr::xlib_surface::NAME,
            W::Xcb { .. } => ash::khr::xcb_surface::NAME,
            W::Wayland { .. } => ash::khr::wayland_surface::NAME,
        };
        if !self.platforms.contains(&needed) {
            eprintln!("kirikae: the Vulkan driver lacks {}; frames are read back instead", needed.to_string_lossy());
            self.present_failed = true;
            return None;
        }
        let (entry, instance) = (&self.entry, &self.instance);
        // SAFETY: the handles come from the live winit window, which stays open for the whole run.
        let made = unsafe {
            match handle {
                W::Win32 { hwnd, hinstance } => ash::khr::win32_surface::Instance::new(entry, instance)
                    .create_win32_surface(&vk::Win32SurfaceCreateInfoKHR::default().hwnd(hwnd).hinstance(hinstance), None),
                W::Xlib { display, window } => ash::khr::xlib_surface::Instance::new(entry, instance)
                    .create_xlib_surface(&vk::XlibSurfaceCreateInfoKHR::default().dpy(display as *mut vk::Display).window(window as vk::Window), None),
                W::Xcb { connection, window } => ash::khr::xcb_surface::Instance::new(entry, instance)
                    .create_xcb_surface(&vk::XcbSurfaceCreateInfoKHR::default().connection(connection as *mut vk::xcb_connection_t).window(window), None),
                W::Wayland { display, surface } => ash::khr::wayland_surface::Instance::new(entry, instance).create_wayland_surface(
                    &vk::WaylandSurfaceCreateInfoKHR::default().display(display as *mut vk::wl_display).surface(surface as *mut vk::wl_surface),
                    None,
                ),
            }
        };
        match made {
            Ok(s) => Some(s),
            Err(e) => {
                eprintln!("kirikae: cannot make a Vulkan surface for the window ({e:?}); frames are read back instead");
                self.present_failed = true;
                None
            }
        }
    }

    pub fn rendered(&self, cpu: u64, width: u32, height: u32) -> bool {
        self.find_image(cpu, width, height, vk::Format::R8G8B8A8_UNORM).is_some_and(|k| self.images[&k].gpu_dirty)
    }
}

#[cfg(test)]
mod tests {
    use super::PresentDump;

    #[test]
    fn present_dump_starts_at_the_requested_successful_present_and_stays_bounded() {
        let mut dump = PresentDump { directory: Default::default(), first: 1, count: u64::MAX, presented: 0 };
        assert!(dump.due());
        dump.presented = 59;
        assert!(!dump.due());
        dump.presented = 60;
        assert!(dump.due());
        dump.first = 1621;
        dump.count = 2;
        for (presented, due) in [(1620, true), (1621, false), (1680, true), (1740, false)] {
            dump.presented = presented;
            assert_eq!(dump.due(), due);
        }
    }
}
