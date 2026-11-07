"""Read Maxwell G24R8 stencil texels as unsigned Vulkan samples."""


def apply(root):
    from .patches import replace_once

    gpu = root / 'crates/rt/src/gpu'
    formats, tic = gpu / 'formats.rs', gpu / 'tic.rs'
    images, textures, descriptors = (gpu / 'vulkan' / name for name in ('images.rs', 'textures.rs', 'descriptors.rs'))

    replace_once(formats, '        (0x0f, FLOAT) => plain(F::R32_SFLOAT, 4),', '''        // G24R8 has an unsigned stencil byte in bits 7:0.
        (0x0e, UINT) if !srgb => integer(F::D24_UNORM_S8_UINT, 4, Kind::Uint),
        (0x0f, FLOAT) => plain(F::R32_SFLOAT, 4),''')

    replace_once(images, 'vk::ImageViewType, u32, u32, u32);', 'vk::ImageViewType, vk::ImageAspectFlags, u32, u32, u32);')
    signature = '    pub(super) fn view_range(&mut self, key: ImageKey, format: vk::Format, swizzle: [vk::ComponentSwizzle; 4], view_type: vk::ImageViewType, levels: (u32, u32), layer: u32) -> vk::ImageView {'
    replace_once(images, signature, signature + '''
        self.view_range_aspect(key, format, swizzle, view_type, aspect_of(format) & !vk::ImageAspectFlags::STENCIL, levels, layer)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn view_range_aspect(&mut self, key: ImageKey, format: vk::Format, swizzle: [vk::ComponentSwizzle; 4],
        view_type: vk::ImageViewType, aspect: vk::ImageAspectFlags, levels: (u32, u32), layer: u32) -> vk::ImageView {''')
    replace_once(images, 'img.views.get(&(format, swizzle, view_type, base, count, layer))',
                 'img.views.get(&(format, swizzle, view_type, aspect, base, count, layer))')
    replace_once(images, 'img.views.insert((format, swizzle, view_type, base, count, layer), v);',
                 'img.views.insert((format, swizzle, view_type, aspect, base, count, layer), v);')
    replace_once(root / 'crates/rt/src/gpu/vulkan/present.rs',
                 'vk::ImageViewType::TYPE_2D, 0, 1, 0);',
                 'vk::ImageViewType::TYPE_2D, vk::ImageAspectFlags::COLOR, 0, 1, 0);')
    replace_once(images, 'aspect_mask: aspect_of(format) & !vk::ImageAspectFlags::STENCIL, base_mip_level: base,',
                 'aspect_mask: aspect, base_mip_level: base,')

    replace_once(tic, '    pub border: [u32; 4],', '    pub border: [u32; 4],\n    pub integer_border: bool,')
    replace_once(tic, '        border: [w[4], w[5], w[6], w[7]],', '        border: [w[4], w[5], w[6], w[7]],\n        integer_border: false,')
    replace_once(textures, '.border_color(border_color(&s.border));', '''.border_color(if s.integer_border {
                match (s.border[0] != 0, s.border[3] != 0) {
                    (true, _) => vk::BorderColor::INT_OPAQUE_WHITE,
                    (false, true) => vk::BorderColor::INT_OPAQUE_BLACK,
                    (false, false) => vk::BorderColor::INT_TRANSPARENT_BLACK,
                }
            } else {
                border_color(&s.border)
            });''')

    replace_once(textures, 'pub(super) const DERIVED: u64 = CROP | GATHER | TWIN | FEEDBACK;', '''const STENCIL_TEXTURE: u64 = 1 << 57;

pub(super) const DERIVED: u64 = CROP | GATHER | TWIN | FEEDBACK | STENCIL_TEXTURE;''')
    replace_once(textures, '        let header = tic::texture_header(&tic);\n        let view_type =', '''        let header = tic::texture_header(&tic);
        if header.components == 0x0e && header.data_type == 4 && !header.srgb {
            if dim != TexDim::D2 || array || shadow || header.texture_type != 1 || header.depth != 1 || header.levels != 1 {
                return Err("stencil texture: unsupported dimensions".into());
            }
            let format = formats::texture(header.components, header.data_type, header.srgb).ok_or("stencil texture: format unavailable")?;
            return self.stencil_texture(gpu, mem, &header, &format, tic::sampler(&tsc))
                .map_err(|why| format!("stencil texture: {why}"));
        }
        let view_type =''')
    replace_once(textures, '    #[allow(clippy::too_many_arguments)]\n    pub(super) fn upload_texture', '''    fn stencil_texture(&mut self, gpu: &Gpu, mem: &GuestMemory, header: &TextureHeader, format: &TexFormat,
        mut sampler: tic::Sampler) -> Result<(vk::ImageView, vk::Sampler), String> {
        let cpu = gpu.translate(header.address).ok_or("not mapped")?;
        self.note_draw_texture_address(cpu);
        let stencil = vk::ImageAspectFlags::STENCIL;
        let target = self.at(cpu).iter().copied().filter(|key| {
            key.width == header.width && key.height == header.height
                && aspect_of(key.format).contains(stencil) && self.images[key].gpu_dirty
        }).max_by_key(|key| self.images[key].stamp);
        let mut components = swizzle(header);
        let view = if let Some(target) = target {
            let key = if self.draw_targets.contains(&target) { self.feedback(target)? } else { target };
            // A stencil read substitutes one for the missing alpha component.
            // Selecting A also works on hosts without depthStencilSwizzleOneSupport.
            components = components.map(|c| if c == vk::ComponentSwizzle::ONE { vk::ComponentSwizzle::A } else { c });
            self.view_range_aspect(key, key.format, components, vk::ImageViewType::TYPE_2D, stencil, (0, 1), 0)
        } else {
            let key = ImageKey { cpu: cpu | STENCIL_TEXTURE, format: vk::Format::R8_UINT, width: header.width, height: header.height };
            if !self.pending.is_empty() && let Some(size) = layer_size(header, format, 1) {
                self.resolve_submitted(cpu, size);
            }
            if self.images.contains_key(&key) {
                self.refresh_texture(gpu, mem, key, header, format, 1);
            } else {
                let hash = texture_hash(gpu, mem, header, format, 1, 1).ok_or("packed texels unreadable")?;
                self.create_image(key, 1, 1).map_err(|e| format!("image: {e:?}"))?;
                self.upload_texture(gpu, mem, key, header, format, 1, 1);
                let frame = crate::display::FRAMES.load(std::sync::atomic::Ordering::Relaxed);
                self.images.get_mut(&key).unwrap().source = Some(Source { hash, checked: frame, volatile: true });
            }
            self.view(key, key.format, components)
        };
        sampler.compare = None;
        sampler.mag_linear = false;
        sampler.min_linear = false;
        sampler.mip = sampler.mip.min(2);
        sampler.max_anisotropy = 1;
        sampler.integer_border = true;
        Ok((view, self.sampler(&sampler)))
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn upload_texture''')
    replace_once(textures, '        let mut data = read_texture(gpu, mem, header, format, levels, layers);', '''        let mut data = read_texture(gpu, mem, header, format, levels, layers);
        if key.cpu & STENCIL_TEXTURE != 0 {
            for (_, _, texels) in &mut data {
                *texels = texels.chunks_exact(4).map(|packed| packed[0]).collect();
            }
        }''')
    replace_once(descriptors, '                    if t.dim == TexDim::D3 || t.shadow {',
                 '                    if t.dim == TexDim::D3 || t.shadow || why.starts_with("stencil texture:") {')
