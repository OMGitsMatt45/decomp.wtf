"""Capture Maxwell vertex stream-out in Vulkan buffers."""

from pathlib import Path


def apply(root):
    from .patches import replace_once

    gpu = root / 'crates/rt/src/gpu'
    vk = gpu / 'vulkan'
    renderer, pipeline, draw = (vk / file for file in ('mod.rs', 'pipeline.rs', 'draw.rs'))
    (vk / 'transform_feedback.rs').write_bytes(Path(__file__).with_name('transform_feedback.rs').read_bytes())
    replace_once(renderer, 'mod textures;', 'mod textures;\nmod transform_feedback;')
    replace_once(renderer, '    rendering: Option<RenderTargets>,', '''    rendering: Option<RenderTargets>,
    transform_feedback: Option<transform_feedback::TransformFeedback>,
    vertex_storage: bool,''')
    replace_once(renderer, '''        let mut supported12 = vk::PhysicalDeviceVulkan12Features::default();
        let mut supported2 = vk::PhysicalDeviceFeatures2::default().push_next(&mut supported12);
        unsafe { instance.get_physical_device_features2(physical, &mut supported2) };''', '''        let xfb_extension = has(ash::ext::transform_feedback::NAME);
        let mut xfb_supported = vk::PhysicalDeviceTransformFeedbackFeaturesEXT::default();
        let mut supported12 = vk::PhysicalDeviceVulkan12Features::default();
        let mut supported2 = vk::PhysicalDeviceFeatures2::default().push_next(&mut supported12);
        if xfb_extension { supported2 = supported2.push_next(&mut xfb_supported); }
        unsafe { instance.get_physical_device_features2(physical, &mut supported2) };
        let xfb_enabled = xfb_supported.transform_feedback == vk::TRUE;
        if xfb_enabled { extensions.push(ash::ext::transform_feedback::NAME.as_ptr()); }
        let mut xfb_feature = vk::PhysicalDeviceTransformFeedbackFeaturesEXT::default().transform_feedback(xfb_enabled);''')
    replace_once(renderer, '            .depth_bias_clamp(supported.depth_bias_clamp == vk::TRUE);', '''            .depth_bias_clamp(supported.depth_bias_clamp == vk::TRUE)
            .vertex_pipeline_stores_and_atomics(supported.vertex_pipeline_stores_and_atomics == vk::TRUE);''')
    replace_once(renderer, '        let device = unsafe { instance.create_device(physical, &info, None)? };', '''        let info = if xfb_enabled { info.push_next(&mut xfb_feature) } else { info };
        let device = unsafe { instance.create_device(physical, &info, None)? };
        let transform_feedback = xfb_enabled.then(|| transform_feedback::TransformFeedback::new(&instance, &device, physical));''')
    replace_once(renderer, '        let buffer = unsafe { device.create_buffer(&vk::BufferCreateInfo::default().size(RING_SIZE).usage(usage), None)? };', '''        let usage = if xfb_enabled { usage | vk::BufferUsageFlags::TRANSFORM_FEEDBACK_BUFFER_EXT } else { usage };
        let buffer = unsafe { device.create_buffer(&vk::BufferCreateInfo::default().size(RING_SIZE).usage(usage), None)? };''')
    replace_once(renderer, '            rendering: None,', '            rendering: None,\n            transform_feedback,\n            vertex_storage: supported.vertex_pipeline_stores_and_atomics == vk::TRUE,')

    replace_once(pipeline, '    pub(super) depth_clamp: bool,', '    pub(super) depth_clamp: bool,\n    pub(super) stream_capture: bool,')
    replace_once(pipeline, '.depth_clamp_enable(key.depth_clamp);',
            '.depth_clamp_enable(key.depth_clamp).rasterizer_discard_enable(key.stream_capture);')

    replace_once(draw, '    pub fn draw(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], draw: Draw) -> bool {',
            '    pub fn draw(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], draw: Draw, cursors: &mut [u64; 4]) -> bool {')
    replace_once(draw, 'let ok = self.try_draw(gpu, mem, regs, cbufs, draw);',
            'let ok = self.try_draw(gpu, mem, regs, cbufs, draw, cursors);')
    replace_once(draw, '    pub(super) fn writes_nothing(&self, regs: &[u32]) -> bool {', '''    pub(super) fn writes_nothing(&self, regs: &[u32]) -> bool {
        if regs[reg::STREAM_OUTPUT] & 1 == 1 {
            return false;
        }''')
    replace_once(draw, '    pub(super) fn try_draw(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], draw: Draw) -> Result<(), String> {',
            '    pub(super) fn try_draw(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], draw: Draw, cursors: &mut [u64; 4]) -> Result<(), String> {')
    replace_once(draw, '        self.guest = mem;\n        self.split();\n        let mut lap = self.clock_start();',
            '        let xfb = self.stream_capture(gpu, mem, regs, draw, cursors)?;\n        self.guest = mem;\n        self.split();\n        if let Some(capture) = &xfb { self.resolve_stream_overlap(capture); }\n        let mut lap = self.clock_start();')
    replace_once(draw, '        let count = (ct & 0xf).min(8);',
                 '        let count = if xfb.is_some() { 0 } else { (ct & 0xf).min(8) };')
    replace_once(draw, '        let depth = self.depth_target(gpu, regs);',
                 '        let depth = if xfb.is_some() { None } else { self.depth_target(gpu, regs) };')
    replace_once(draw, '        if targets.is_empty() && depth.is_none() {', '''        if xfb.is_some() {
            // Rasterization is disabled for stream-out. Stale framebuffer bindings
            // have no role in this draw.
            sizes.push((1, 1));
        } else if targets.is_empty() && depth.is_none() {''')
    replace_once(draw, '            let viewport = viewport(regs, extent);', '''            let viewport = if xfb.is_some() {
                vk::Viewport { width: 1.0, height: 1.0, max_depth: 1.0, ..Default::default() }
            } else {
                viewport(regs, extent)
            };''')
    replace_once(draw, '            let scissor = if regs[reg::SCISSOR] & 1 == 1 {',
                 '            let scissor = if xfb.is_none() && regs[reg::SCISSOR] & 1 == 1 {')
    replace_once(draw, '        let cs = self.shader(gpu, mem, regs, va, Stage::Compute, cbufs, [Kind::Float; 32], [Kind::Float; 8], Some(qmd))?;',
            '        let cs = self.shader(gpu, mem, regs, va, Stage::Compute, cbufs, [Kind::Float; 32], [Kind::Float; 8], Some(qmd), None)?;')
    replace_once(draw, 'let vs = self.shader(gpu, mem, regs, shader_va(1), Stage::Vertex, cbufs[0], attribute_types, output_types, None)?;',
            'let vs = self.shader(gpu, mem, regs, shader_va(1), Stage::Vertex, cbufs[0], attribute_types, output_types, None, xfb.as_ref().map(|capture| &capture.layout))?;')
    replace_once(draw, 'shader_va(5), Stage::Fragment, cbufs[4], attribute_types, output_types, None)?',
            'shader_va(5), Stage::Fragment, cbufs[4], attribute_types, output_types, None, None)?')
    replace_once(draw, '        let exports_depth = fs.as_ref()', '''        if !self.vertex_storage && (vs.shader.storage != 0 || !vs.shader.images.is_empty()) {
            return Err("Vulkan vertex shader storage requires vertexPipelineStoresAndAtomics".into());
        }
        let exports_depth = fs.as_ref()''')
    replace_once(draw, '        key.depth_clamp =', '        key.stream_capture = xfb.is_some();\n        key.depth_clamp =')
    replace_once(draw, '        let lowest = range.map_or(0, |r| r.0);', '''        let lowest = range.map_or(0, |r| r.0);
        let xfb_offset = xfb.as_ref().map(|capture| self.reserve_stream_capture(capture)).transpose()?;''')
    replace_once(draw, '        self.bind_descriptors(vk::PipelineBindPoint::GRAPHICS, set_layout, layout, &descriptors, &mut scratch);', '''        self.bind_descriptors(vk::PipelineBindPoint::GRAPHICS, set_layout, layout, &descriptors, &mut scratch);
        let capture = xfb.as_ref().zip(xfb_offset);
        if let Some((xfb, offset)) = capture { self.begin_stream_capture(xfb, offset); }''')
    replace_once(draw, '        if fs.as_ref().is_some_and(|s| s.shader.images.iter().any(|image| image.atomic_u32)) {', '''        if let Some((xfb, offset)) = capture {
            self.end_stream_capture(xfb, offset, cursors);
        } else if fs.as_ref().is_some_and(|s| s.shader.images.iter().any(|image| image.atomic_u32)) {''')

    threed = gpu / 'threed.rs'
    replace_once(threed, 'pub mod reg {', '''pub mod reg {
    pub const RASTER_ENABLE: usize = 0x37c / 4;
    pub const STREAM_OUTPUT: usize = 0x744 / 4;
    pub const STREAM_WRITE_POINTER: usize = 0x390 / 4;''')
    replace_once(threed, '''    pub constant_buffers: [[Option<(u64, u32)>; CB_SLOTS]; 5],
}''', '''    pub constant_buffers: [[Option<(u64, u32)>; CB_SLOTS]; 5],
    pub stream_cursors: [u64; 4],
}

impl State {
    pub(super) fn load_stream_pointer(&mut self, method: usize, value: u32) {
        if let Some(slot) = method.checked_sub(reg::STREAM_WRITE_POINTER).filter(|n| *n < 32 && n.is_multiple_of(8)) {
            self.stream_cursors[slot / 8] = u64::from(value);
        }
    }
}''')
    replace_once(threed, '    pub(super) fn threed(&self, mem: &GuestMemory, e: &mut Engines, m: u32, v: u32) {', '''    pub(super) fn threed(&self, mem: &GuestMemory, e: &mut Engines, m: u32, v: u32) {
        e.threed.load_stream_pointer(m as usize, v);''')
    direct_draw = 'self.draw(mem, &e.regs[&super::CLASS_3D], &cbs, draw);'
    source = threed.read_text(encoding='utf-8')
    if source.count(direct_draw) != 3:
        raise ValueError('Switch stream-out draw dispatch no longer applies: ' + str(threed))
    threed.write_text(source.replace(direct_draw, direct_draw.replace('draw);', 'draw, &mut e.threed.stream_cursors);')),
                      encoding='utf-8', newline='\n')
    replace_once(threed, 'cbs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], mut draw: Draw) {',
            'cbs: &[[Option<(u64, u32)>; CB_SLOTS]; 5], mut draw: Draw, cursors: &mut [u64; 4]) {')
    replace_once(threed, 'self.with_renderer(|r| r.draw(self, mem, regs, cbs, draw));',
            'self.with_renderer(|r| r.draw(self, mem, regs, cbs, draw, cursors));')
    gpu_mod = gpu / 'mod.rs'
    replace_once(gpu_mod, 'self.draw(mem, &eng.regs[&CLASS_3D], &cbs, d);',
            'self.draw(mem, &eng.regs[&CLASS_3D], &cbs, d, &mut eng.threed.stream_cursors);')
    replace_once(gpu_mod, '''                        regs[r] = regs[r] & !mask | v;
                    }
                }
                Step::Bind { group, slot, binding } => eng.threed''', '''                        regs[r] = regs[r] & !mask | v;
                        eng.threed.load_stream_pointer(r, regs[r]);
                    }
                }
                Step::Bind { group, slot, binding } => eng.threed''')
