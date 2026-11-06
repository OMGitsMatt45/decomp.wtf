"""Clear the Maxwell color attachment slice selected by CLEAR_SURFACE."""


def apply(root):
    from .patches import replace_once

    gpu = root / 'crates/rt/src/gpu'
    threed = gpu / 'threed.rs'
    images = gpu / 'vulkan/images.rs'
    replace_once(threed, '''        let rt = (v >> 6 & 0xf) as usize;
        let base = reg::COLOR_TARGET + rt * 0x10;''', '''        let rt = (v >> 6 & 0xf) as usize;
        if rt >= 8 { return; }
        // NVB197 CLEAR_SURFACE RT_ARRAY_INDEX occupies bits 25:10.
        let array_index = (v >> 10) & 0xffff;
        let base = reg::COLOR_TARGET + rt * 0x10;''')
    replace_once(threed, '                v >> 10 & 0x7ff,', '                array_index,')
    replace_once(threed, '        let surface = super::vulkan::color_surface(regs, base);\n        let bits =',
                 '        let bits =')
    replace_once(threed, '''        let rendered = self.with_renderer(|r| r.clear(self, mem, regs, &surface, bits)).is_some();
        if rendered && crate::env_var!("KIRIKAE_CPU_CLEARS").is_none() {''', '''        let rendered = self.with_renderer(|r| r.clear(self, mem, regs, base, array_index, bits)).is_some();
        // The CPU fill only describes one 2D surface at the base address.
        if (rendered && crate::env_var!("KIRIKAE_CPU_CLEARS").is_none())
            || regs[base + 6] & 0x0fff_ffff > 1 || regs[base + 8] & 0xffff != 0 || array_index != 0
        {''')

    replace_once(images, '''    pub fn clear(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], s: &Surface, color: [u32; 4]) {
        let Some((key, fmt)) = self.surface_image(gpu, mem, s, false) else { return };''', '''    pub fn clear(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], base: usize,
        array_index: u32, color: [u32; 4]) {
        let count = (regs[base + 6] & 0x0fff_ffff).max(1);
        // The clear index is relative to SET_COLOR_TARGET_LAYER.
        let layer = (regs[base + 8] & 0xffff) + array_index;
        if layer >= count { return; }
        let surface = color_surface(regs, base);
        let attachment = if count == 1 {
            self.surface_image(gpu, mem, &surface, false)
        } else {
            self.color_attachment(gpu, mem, regs, base, &surface, count)
        };
        let Some((key, fmt)) = attachment else { return };''')
    replace_once(images, '''            Some(rect) => {
                let view = self.view(key, fmt.vk, IDENTITY);
                let attachment = [vk::RenderingAttachmentInfo::default()''', '''            Some(rect) => {
                let view = self.view_range(key, fmt.vk, IDENTITY, vk::ImageViewType::TYPE_2D, (0, 1), layer);
                let attachment = [vk::RenderingAttachmentInfo::default()''')
    replace_once(images, '''                let range = [vk::ImageSubresourceRange { aspect_mask: vk::ImageAspectFlags::COLOR, base_mip_level: 0, level_count: 1, base_array_layer: 0, layer_count: 1 }];
                let image = self.images[&key].image;
                unsafe { self.device.cmd_clear_color_image''', '''                let range = [vk::ImageSubresourceRange { aspect_mask: vk::ImageAspectFlags::COLOR, base_mip_level: 0, level_count: 1, base_array_layer: layer, layer_count: 1 }];
                let image = self.images[&key].image;
                unsafe { self.device.cmd_clear_color_image''')
    replace_once(images, '''                unsafe { self.device.cmd_clear_color_image(self.cmd, image, vk::ImageLayout::GENERAL, &value, &range) };
            }
        }
        self.barrier();
        self.touch(key);
        if area.is_none() {''', '''                unsafe { self.device.cmd_clear_color_image(self.cmd, image, vk::ImageLayout::GENERAL, &value, &range) };
            }
        }
        self.barrier();
        self.touch(key);
        if area.is_none() && self.images[&key].layers == 1 {''')
