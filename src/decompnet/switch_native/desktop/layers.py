"""Map Maxwell layer attributes and color targets to Vulkan layered draws."""


def apply(root):
    from .patches import replace_once

    maxwell = root / 'crates/maxwell/src/translate.rs'
    vk = root / 'crates/rt/src/gpu/vulkan'
    renderer, pipeline, draw, images, volumes = (vk / name for name in (
        'mod.rs', 'pipeline.rs', 'draw.rs', 'images.rs', 'volumes.rs'))
    replace_once(maxwell, '    pub const POINT_SIZE: u32 = 0x6c;', '''    pub const LAYER: u32 = 0x64;
    pub const POINT_SIZE: u32 = 0x6c;''')
    replace_once(maxwell, '    pub exact_texel_rounding: bool,', '''    pub exact_texel_rounding: bool,
    pub shader_layer: bool,''')
    replace_once(maxwell, '            exact_texel_rounding: false,', '''            exact_texel_rounding: false,
            shader_layer: false,''')
    replace_once(maxwell, '        self.interface.push(var);\n        self.builtins.insert(key, var);', '''        if !output && which == BuiltIn::Layer {
            self.b.decorate(var, Decoration::Flat, []);
        }
        self.interface.push(var);
        self.builtins.insert(key, var);''')
    replace_once(maxwell, '            attr::FRONT_FACING if self.opts.stage == Stage::Fragment => {', '''            attr::LAYER if self.opts.stage == Stage::Fragment && self.opts.shader_layer => {
                let var = self.builtin(BuiltIn::Layer, self.t.i32, false);
                let layer = self.b.load(self.t.i32, None, var, None, [])?;
                self.cast_u(layer)
            }
            attr::FRONT_FACING if self.opts.stage == Stage::Fragment => {''')
    replace_once(maxwell, '            attr::POINT_SIZE | 0x64 | 0x68 | 0x2c0..=0x2dc => Ok(()),', '''            attr::LAYER if self.opts.stage == Stage::Vertex && self.opts.shader_layer => {
                let var = self.builtin(BuiltIn::Layer, self.t.i32, true);
                let layer = self.b.bitcast(self.t.i32, None, v)?;
                self.b.store(var, layer, None, [])?;
                Ok(())
            }
            attr::POINT_SIZE | 0x68 | 0x2c0..=0x2dc => Ok(()),''')
    replace_once(maxwell, '        let interface = self.interface.clone();', '''        let interface = if [BuiltIn::Layer as u32, BuiltIn::Layer as u32 | (1 << 31)]
            .iter().any(|key| self.builtins.contains_key(key)) {
            self.b.set_version(1, 5);
            self.b.capability(Capability::ShaderLayer);
            // SPIR-V 1.4+ includes all global variables in the entry interface.
            self.b.module_ref().types_global_values.iter()
                .filter(|i| i.class.opcode == rspirv::spirv::Op::Variable)
                .filter_map(|i| i.result_id).collect()
        } else {
            self.interface.clone()
        };''')
    tests = root / 'crates/maxwell/tests/translate.rs'
    with tests.open('a', encoding='utf-8', newline='\n') as out:
        out.write('''
#[test]
fn layer_shaders_use_integer_interfaces() {
    let read_layer = (ipa(0, 0x64, 0xff) & !(3 << 54)) | 2 << 54;
    for (stage, header, insn) in [
        (Stage::Vertex, vertex_header(), ast(0, 0x64, 1)),
        (Stage::Fragment, fragment_header(1), read_layer),
    ] {
        let mut options = options(stage);
        options.shader_layer = true;
        let code = program(header, &[mov32i(0, 3), insn, EXIT]);
        let shader = translate(&code, &options, &kirikae_maxwell::NoEnv).unwrap();
        assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
        let spirv = disassemble(&shader.spirv);
        assert!(spirv.contains("OpCapability ShaderLayer"), "{spirv}");
        assert!(spirv.lines().any(|line| line.contains("BuiltIn Layer")), "{spirv}");
        if stage == Stage::Fragment {
            assert!(spirv.lines().any(|line| line.contains(" Flat")), "{spirv}");
        }
        // Naga does not support ShaderLayer. Check the SPIR-V 1.5 interface here.
        let mut loader = rspirv::dr::Loader::new();
        rspirv::binary::parse_words(&shader.spirv, &mut loader).unwrap();
        let module = loader.module();
        assert_eq!(shader.spirv[1], 0x0001_0500);
        let interface = &module.entry_points[0].operands[3..];
        for var in module.types_global_values.iter().filter(|i| i.class.opcode == rspirv::spirv::Op::Variable) {
            assert!(interface.contains(&rspirv::dr::Operand::IdRef(var.result_id.unwrap())));
        }
        variables_first(&shader.spirv);
    }
}
''')
    replace_once(renderer, '    pub software: bool,', '''    pub software: bool,
    shader_layer: bool,''')
    replace_once(renderer, '        let mut v13 = vk::PhysicalDeviceVulkan13Features::default().dynamic_rendering(true);', '''        let mut supported12 = vk::PhysicalDeviceVulkan12Features::default();
        let mut supported2 = vk::PhysicalDeviceFeatures2::default().push_next(&mut supported12);
        unsafe { instance.get_physical_device_features2(physical, &mut supported2) };
        let shader_layer = supported12.shader_output_layer == vk::TRUE;
        let mut v12 = vk::PhysicalDeviceVulkan12Features::default().shader_output_layer(shader_layer);
        let mut v13 = vk::PhysicalDeviceVulkan13Features::default().dynamic_rendering(true);''')
    replace_once(renderer, '.enabled_features(&features).push_next(&mut v13);',
                 '.enabled_features(&features).push_next(&mut v12).push_next(&mut v13);')
    replace_once(renderer, '            software: props.device_type == vk::PhysicalDeviceType::CPU,', '''            software: props.device_type == vk::PhysicalDeviceType::CPU,
            shader_layer,''')
    replace_once(pipeline, '            exact_texel_rounding: crate::env_var!("KIRIKAE_NO_TEXEL_ROUNDING").is_some(),', '''            exact_texel_rounding: crate::env_var!("KIRIKAE_NO_TEXEL_ROUNDING").is_some(),
            shader_layer: self.shader_layer,''')

    replace_once(draw, 'pub(super) type TargetAsk = (u64, vk::Format, u32, u32, u64);',
                 'pub(super) type TargetAsk = (u64, vk::Format, u32, u32, u32, u64);')
    replace_once(renderer, '((u64::MAX, vk::Format::UNDEFINED, 0, 0, u64::MAX), ImageKey',
                 '((u64::MAX, vk::Format::UNDEFINED, 0, 0, 0, u64::MAX), ImageKey')
    replace_once(images, '''    pub(super) fn create_image(&mut self, key: ImageKey, levels: u32, layers: u32) -> Result<(), vk::Result> {
        let usage''', '''    pub(super) fn create_image(&mut self, key: ImageKey, levels: u32, layers: u32) -> Result<(), vk::Result> {
        let image = self.allocate_image(key, levels, layers)?;
        self.install_image(key, image);
        Ok(())
    }

    fn allocate_image(&mut self, key: ImageKey, levels: u32, layers: u32) -> Result<Image, vk::Result> {
        let usage''')
    replace_once(images, '''        self.clock += 1;
        self.images.insert(key, Image { image, memory, views: HashMap::default(), levels: levels.max(1), layers: layers.max(1), gpu_dirty: false, stamp: self.clock, source: None, drawn: None, cleared: None, clear_streak: 0 });
        if key.cpu & DERIVED == 0 {''', '''        Ok(Image { image, memory, views: HashMap::default(), levels: levels.max(1), layers: layers.max(1), gpu_dirty: false, stamp: 0, source: None, drawn: None, cleared: None, clear_streak: 0 })
    }

    fn install_image(&mut self, key: ImageKey, mut image: Image) {
        self.clock += 1;
        image.stamp = self.clock;
        let layered = image.layers > 1;
        self.images.insert(key, image);
        if key.cpu & DERIVED == 0 {''')
    replace_once(images, '            self.forget_textures(key.cpu, layers > 1);',
                 '            self.forget_textures(key.cpu, layered);')
    replace_once(images, '''        if !at.contains(&key) {
            at.push(key);
        }
        Ok(())''', '''        if !at.contains(&key) {
            at.push(key);
        }''')
    replace_once(images, '''        let asked = (cpu, format, width, height, self.generation);''', '''        self.target_array_image(cpu, format, width, height, 1, || Some(Vec::new()))
    }

    fn target_array_image(&mut self, cpu: u64, format: vk::Format, width: u32, height: u32, layers: u32,
        read: impl FnOnce() -> Option<Vec<(u32, u32, Vec<u8>)>>) -> Option<(ImageKey, bool)> {
        let asked = (cpu, format, width, height, layers, self.generation);''')
    replace_once(images, '''find(|k| k.format == format && k.width >= width && k.height >= height) {''', '''find(|k| {
            k.format == format && k.width >= width && k.height >= height && self.images[k].layers >= layers
        }) {''')
    replace_once(images, '''        for k in same_format.into_iter().chain(evicted) {''', '''        let data = read()?;
        let key = ImageKey { cpu, format, width: w, height: h };
        let mut replacement = self.allocate_image(key, 1, layers).ok()?;
        if !data.is_empty() {
            self.upload_to_image(replacement.image, format, 1, &data);
            // Guest memory can lag the GPU when an existing target grows.
            // Retain written slices before retiring the smaller attachment.
            let mut written: Vec<_> = same_format.iter().filter(|k| self.images[k].gpu_dirty).copied().collect();
            written.sort_by_key(|k| self.images[k].stamp);
            for old in written {
                let previous = &self.images[&old];
                let subresource = vk::ImageSubresourceLayers { aspect_mask: vk::ImageAspectFlags::COLOR,
                    mip_level: 0, base_array_layer: 0, layer_count: previous.layers.min(layers) };
                let region = [vk::ImageCopy::default().src_subresource(subresource).dst_subresource(subresource)
                    .extent(vk::Extent3D { width: old.width, height: old.height, depth: 1 })];
                let source = previous.image;
                self.barrier();
                unsafe { self.device.cmd_copy_image(self.cmd, source, vk::ImageLayout::GENERAL,
                    replacement.image, vk::ImageLayout::GENERAL, &region) };
                replacement.gpu_dirty = true;
            }
            self.barrier();
        }
        for k in same_format.into_iter().chain(evicted) {''')
    replace_once(images, '''        let key = ImageKey { cpu, format, width: w, height: h };
        self.create_image(key, 1, 1).ok()?;
        Some((key, true))''', '''        self.install_image(key, replacement);
        Some((key, true))''')
    replace_once(images, '''    pub(super) fn upload_layers(&mut self, key: ImageKey, per_layer: usize, levels: &[(u32, u32, Vec<u8>)]) {
        self.begin();''', '''    pub(super) fn upload_layers(&mut self, key: ImageKey, per_layer: usize, levels: &[(u32, u32, Vec<u8>)]) {
        self.upload_to_image(self.images[&key].image, key.format, per_layer, levels);
        self.clock += 1;
        self.images.get_mut(&key).unwrap().stamp = self.clock;
        self.restamped(key);
    }

    fn upload_to_image(&mut self, image: vk::Image, format: vk::Format, per_layer: usize, levels: &[(u32, u32, Vec<u8>)]) {
        self.begin();''')
    replace_once(images, '''aspect_of(key.format) & !vk::ImageAspectFlags::STENCIL, mip_level: level as u32''',
                 '''aspect_of(format) & !vk::ImageAspectFlags::STENCIL, mip_level: level as u32''')
    replace_once(images, '''        let image = self.images[&key].image;
        self.barrier();
        unsafe { self.device.cmd_copy_buffer_to_image(self.cmd, self.ring.buffer, image, vk::ImageLayout::GENERAL, &regions) };
        self.barrier();
        self.stats.uploads += 1;
        self.clock += 1;
        self.images.get_mut(&key).unwrap().stamp = self.clock;
        self.restamped(key);''', '''        self.barrier();
        unsafe { self.device.cmd_copy_buffer_to_image(self.cmd, self.ring.buffer, image, vk::ImageLayout::GENERAL, &regions) };
        self.barrier();
        self.stats.uploads += 1;''')
    replace_once(images, '    pub(super) fn destroy_image(&mut self, key: ImageKey) {', '''    pub(super) fn color_attachment(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], base: usize,
        s: &Surface, layers: u32) -> Option<(ImageKey, ColorFormat)> {
        if layers == 1 {
            return self.surface_image(gpu, mem, s, true);
        }
        let limit = unsafe { self.instance.get_physical_device_properties(self.physical) }.limits.max_image_array_layers;
        if s.width == 0 || s.height == 0 || layers > limit {
            return None;
        }
        let format = formats::color_target(s.format)?;
        let cpu = gpu.translate(s.va)?;
        let (key, _) = self.target_array_image(cpu, format.vk, s.width, s.height, layers, || {
            if regs[base + 5] & (1 << 16) != 0 {
                use super::tiling::{deswizzle_3d, volume_size};
                let depth = (regs[base + 5] >> 8) & 7;
                let size = volume_size(s.width, s.height, layers, format.bytes, s.block_height_log2, depth);
                let raw = gpu.read(mem, s.va, size)?;
                let bytes = deswizzle_3d(&raw, s.width, s.height, layers, format.bytes, s.block_height_log2, depth);
                let slice = (s.width as usize).checked_mul(s.height as usize)?.checked_mul(format.bytes as usize)?;
                Some(bytes.chunks_exact(slice).map(|data| (s.width, s.height, data.to_vec())).collect())
            } else {
                let stride = u64::from(regs[base + 7]) * 4;
                if stride == 0 { return None; }
                (0..layers).map(|layer| {
                    let va = s.va.checked_add(u64::from(layer) * stride)?;
                    let data = read_surface(gpu, mem, &Surface { va, ..*s }, format.bytes)?;
                    Some((s.width, s.height, data))
                }).collect::<Option<Vec<_>>>()
            }
        })?;
        Some((key, format))
    }

    pub(super) fn destroy_image(&mut self, key: ImageKey) {''')

    replace_once(draw, '    pub(super) extent: (u32, u32),', '''    pub(super) extent: (u32, u32),
    layers: u32,''')
    replace_once(draw, '        let mut output_types = [Kind::Float; 8];', '''        let mut output_types = [Kind::Float; 8];
        let mut first_layers = [0; 8];
        let mut attachment_layers = None;''')
    replace_once(draw, '''            let (key, fmt) = self.surface_image(gpu, mem, &s, true).ok_or_else(|| format!("render target format {format:#x}"))?;''', '''            let count = (regs[base + 6] & 0x0fff_ffff).max(1);
            let first = regs[base + 8] & 0xffff;
            if first >= count {
                return Err(format!("render target starts at layer {first} of {count}"));
            }
            let (key, fmt) = self.color_attachment(gpu, mem, regs, base, &s, count)
                .ok_or_else(|| format!("render target format {format:#x}"))?;
            first_layers[k as usize] = first;
            let available = count - first;
            attachment_layers = Some(attachment_layers.map_or(available, |layers: u32| layers.min(available)));''')
    replace_once(draw, '''        if targets.is_empty() && depth.is_none() {
            return Err("no color or depth target".into());
        }''', '''        let mut empty_viewport = false;
        if targets.is_empty() && depth.is_none() {
            // Attachmentless draws can still run shaders and write storage.
            let viewport = viewport(regs, (0, 0));
            let right = viewport.x.max(viewport.x + viewport.width).ceil();
            let bottom = viewport.y.max(viewport.y + viewport.height).ceil();
            empty_viewport = viewport.width == 0.0 || viewport.height == 0.0;
            if !empty_viewport {
                let limits = unsafe { self.instance.get_physical_device_properties(self.physical) }.limits;
                if !(1.0..=limits.max_framebuffer_width as f32).contains(&right)
                    || !(1.0..=limits.max_framebuffer_height as f32).contains(&bottom) {
                    return Err("attachmentless draw has no valid viewport".into());
                }
            }
            sizes.push((right as u32, bottom as u32));
        }
        let layers = if depth.is_some() { 1 } else { attachment_layers.unwrap_or(1) };''')
    replace_once(draw, '        let exports_depth = fs.as_ref().is_some_and(|f| f.shader.writes_depth);', '''        if empty_viewport {
            let writes = std::iter::once(&vs).chain(fs.as_ref())
                .any(|s| s.shader.storage_written != 0 || !s.shader.images.is_empty());
            let extra_stages = [0, 2, 3, 4].iter().any(|s| regs[reg::PIPELINE + 16 * s] & 1 != 0);
            // Maxwell transform feedback enable is method 0x744.
            if writes || extra_stages || regs[0x744 / 4] != 0 {
                return Err("empty attachmentless draw has shader side effects".into());
            }
            self.stats.noop_draws += 1;
            return Ok(());
        }
        let exports_depth = fs.as_ref().is_some_and(|f| f.shader.writes_depth);''')
    replace_once(draw, '''        for t in &targets {
            views.push(match *t {
                Some((k, f)) => (self.view(k, f.vk, IDENTITY), f.vk),''', '''        for (i, t) in targets.iter().enumerate() {
            views.push(match *t {
                Some((k, f)) => {
                    let view_type = if layers > 1 { vk::ImageViewType::TYPE_2D_ARRAY } else { vk::ImageViewType::TYPE_2D };
                    (self.view_range(k, f.vk, IDENTITY, view_type, (0, 1), first_layers[i]), f.vk)
                }''')
    replace_once(draw, 'r.depth == depth_view && r.extent == extent)',
                 'r.depth == depth_view && r.extent == extent && r.layers == layers)')
    replace_once(draw, 'let rt = RenderTargets { views: views.clone(), depth: depth_view, extent };',
                 'let rt = RenderTargets { views: views.clone(), depth: depth_view, extent, layers };')
    replace_once(draw, '                .layer_count(1)', '                .layer_count(layers)')

    replace_once(volumes, '''            let sources: Vec<Option<ImageKey>> = (0..d as u64)
                .map(|z| self.rendered_slice(cpu + (z >> bd) * blocks_high * gobs_wide * block_size + ((z & ((1 << bd) - 1)) << bh) * 512, format.vk, w, h))
                .collect();''', '''            let layered = self.rendered_slice(cpu, format.vk, w, h)
                .filter(|key| self.images[key].layers >= d);
            let sources: Vec<_> = (0..d as u64)
                .map(|z| {
                    let address = cpu + (z >> bd) * blocks_high * gobs_wide * block_size + ((z & ((1 << bd) - 1)) << bh) * 512;
                    let separate = self.rendered_slice(address, format.vk, w, h);
                    self.latest_slice(layered, z as u32, separate)
                }).collect();''')
    replace_once(volumes, '''            let sources: Vec<Option<ImageKey>> = (0..d as u64).map(|z| self.rendered_slice(cpu + z * stride, format.vk, w, h)).collect();''', '''            let layered = self.rendered_slice(cpu, format.vk, w, h)
                .filter(|key| self.images[key].layers >= d);
            let sources: Vec<_> = (0..d as u64).map(|z| {
                let separate = self.rendered_slice(cpu + z * stride, format.vk, w, h);
                self.latest_slice(layered, z as u32, separate)
            }).collect();''')
    replace_once(volumes, '''    fn copy_slices(&mut self, key: (u64, vk::Format), sources: &[Option<ImageKey>], w: u32, h: u32) {''', '''    fn latest_slice(&self, layered: Option<ImageKey>, layer: u32, separate: Option<ImageKey>) -> Option<(ImageKey, u32)> {
        separate.filter(|key| Some(*key) != layered).map(|key| (key, 0)).into_iter()
            .chain(layered.map(|key| (key, layer)))
            .max_by_key(|(key, _)| self.images[key].stamp)
    }

    fn copy_slices(&mut self, key: (u64, vk::Format), sources: &[Option<(ImageKey, u32)>], w: u32, h: u32) {''')
    replace_once(volumes, 's.map_or(0, |k| self.images[&k].stamp)', 's.map_or(0, |(key, _)| self.images[&key].stamp)')
    replace_once(volumes, '''            let Some(src) = src else { continue };
            let region = [vk::ImageCopy::default().src_subresource(sub).dst_subresource(sub)''', '''            let Some((src, layer)) = src else { continue };
            let source = vk::ImageSubresourceLayers { base_array_layer: *layer, ..sub };
            let region = [vk::ImageCopy::default().src_subresource(source).dst_subresource(sub)''')
