"""Map logical Maxwell raster coordinates to the physical sample grid."""


def apply(root):
    from .patches import replace_once

    gpu = root / 'crates/rt/src/gpu'
    threed = gpu / 'threed.rs'
    replace_once(threed, '    pub const PROGRAM_REGION: usize = 0x582;', '''    pub const ANTI_ALIAS: usize = 0x574;
    pub const PROGRAM_REGION: usize = 0x582;''')
    replace_once(threed, 'pub fn address(regs: &[u32], at: usize) -> u64 {', '''// Render targets are backed by single-sample images sized in guest samples.
// SET_ANTI_ALIAS selects their layout independently of coverage sampling.
pub(super) fn sample_grid(regs: &[u32]) -> [u32; 2] {
    match regs[reg::ANTI_ALIAS] & 0xf {
        1 | 5 => [2, 1],
        2 | 8 | 9 => [2, 2],
        3 | 4 | 10 | 11 => [4, 2],
        6 => [4, 4],
        _ => [1, 1],
    }
}

pub(super) fn scissor_bounds(regs: &[u32], extent: (u32, u32)) -> [u32; 4] {
    let (h, v) = (regs[reg::SCISSOR + 1], regs[reg::SCISSOR + 2]);
    let [sx, sy] = sample_grid(regs);
    [((h & 0xffff) * sx).min(extent.0), ((v & 0xffff) * sy).min(extent.1),
        ((h >> 16) * sx).min(extent.0), ((v >> 16) * sy).min(extent.1)]
}

pub fn address(regs: &[u32], at: usize) -> u64 {''')

    draw = gpu / 'vulkan/draw.rs'
    replace_once(draw, 'CB_SLOTS, Draw, address, reg', 'CB_SLOTS, Draw, address, reg, sample_grid, scissor_bounds')
    replace_once(draw, 'pub(super) type TargetAsk', '''fn viewport(regs: &[u32], extent: (u32, u32)) -> vk::Viewport {
    let [gx, gy] = sample_grid(regs).map(|factor| factor as f32);
    let read = |k| f32::from_bits(regs[reg::VIEWPORT_SCALE + k]);
    let (sx, sy, ox, oy) = (read(0), read(1), read(3), read(4));
    if sx == 0.0 {
        vk::Viewport { x: 0.0, y: 0.0, width: extent.0 as f32, height: extent.1 as f32, min_depth: 0.0, max_depth: 1.0 }
    } else {
        vk::Viewport { x: (ox - sx) * gx, y: (oy - sy) * gy, width: 2.0 * sx * gx, height: 2.0 * sy * gy, min_depth: 0.0, max_depth: 1.0 }
    }
}

pub(super) type TargetAsk''')
    replace_once(draw, '''            let sx = f32::from_bits(regs[reg::VIEWPORT_SCALE]);
            let sy = f32::from_bits(regs[reg::VIEWPORT_SCALE + 1]);
            let ox = f32::from_bits(regs[reg::VIEWPORT_SCALE + 3]);
            let oy = f32::from_bits(regs[reg::VIEWPORT_SCALE + 4]);
            let viewport = vk::Viewport { x: ox - sx, y: oy - sy, width: 2.0 * sx, height: 2.0 * sy, min_depth: 0.0, max_depth: 1.0 };
            let viewport = if viewport.width == 0.0 {
                vk::Viewport { x: 0.0, y: 0.0, width: extent.0 as f32, height: extent.1 as f32, min_depth: 0.0, max_depth: 1.0 }
            } else {
                viewport
            };''', '''            let viewport = viewport(regs, extent);''')
    replace_once(draw, '''                let (h, v) = (regs[reg::SCISSOR + 1], regs[reg::SCISSOR + 2]);
                let (x0, x1) = ((h & 0xffff).min(extent.0), (h >> 16).min(extent.0));
                let (y0, y1) = ((v & 0xffff).min(extent.1), (v >> 16).min(extent.1));''',
                 '                let [x0, y0, x1, y1] = scissor_bounds(regs, extent);')
    replace_once(draw, '"gpu: draw state: origin {:#x} cull', '"gpu: draw state: origin {:#x} AA mode {:#x} grid {:?} cull')
    replace_once(draw, '                regs[0x4eb],', '                regs[0x4eb],\n                regs[reg::ANTI_ALIAS],\n                sample_grid(regs),')

    images = gpu / 'vulkan/images.rs'
    replace_once(images, '''    let (h, v) = (regs[reg::SCISSOR + 1], regs[reg::SCISSOR + 2]);
    let (x0, x1) = ((h & 0xffff).min(key.width), (h >> 16).min(key.width));
    let (y0, y1) = ((v & 0xffff).min(key.height), (v >> 16).min(key.height));''',
                 '    let [x0, y0, x1, y1] = crate::gpu::threed::scissor_bounds(regs, (key.width, key.height));')

    pipeline = gpu / 'vulkan/pipeline.rs'
    replace_once(pipeline, '    pub(super) types: u64,', '''    pub(super) types: u64,
    pub(super) fragment_sample_grid: [u32; 2],''')
    replace_once(pipeline, '        let key = ShaderKey { va, hash: head, stage: stage as u8, types };', '''        let fragment_sample_grid = if stage == Stage::Fragment { crate::gpu::threed::sample_grid(regs) } else { [1, 1] };
        let key = ShaderKey { va, hash: head, stage: stage as u8, types, fragment_sample_grid };''')
    replace_once(pipeline, '            depth_unorm16,\n            alpha_test,', '            depth_unorm16,\n            fragment_sample_grid,\n            alpha_test,')

    maxwell = root / 'crates/maxwell/src/translate.rs'
    replace_once(maxwell, '    pub depth_unorm16: bool,', '    pub depth_unorm16: bool,\n    pub fragment_sample_grid: [u32; 2],')
    replace_once(maxwell, '            depth_unorm16: false,', '            depth_unorm16: false,\n            fragment_sample_grid: [1, 1],')
    for question in ('', '?'):
        replace_once(maxwell, '''                let v4f = self.t.v4f;
                let var = self.builtin(BuiltIn::FragCoord, v4f, false);
                self.component(var, Kind::Float, StorageClass::Input, (addr - attr::POSITION) / 4)'''
                     + question + '\n            }',
                     '                self.fragment_position((addr - attr::POSITION) / 4)' + question + '\n            }')
    replace_once(maxwell, '    fn ipa(&mut self, i: &Insn) -> R {', '''    fn fragment_position(&mut self, channel: u32) -> R<Word> {
        let var = self.builtin(BuiltIn::FragCoord, self.t.v4f, false);
        let value = self.component(var, Kind::Float, StorageClass::Input, channel)?;
        let Some(&samples) = self.opts.fragment_sample_grid.get(channel as usize).filter(|&&factor| factor > 1) else {
            return Ok(value);
        };
        // Evaluate each physical sample with its guest pixel's logical center.
        let value = self.cast_f(value)?;
        let inverse = self.f(1.0 / samples as f32);
        let pixel = self.b.f_mul(self.t.f32, None, value, inverse)?;
        let pixel = self.ext(self.t.f32, glsl::FLOOR, &[pixel])?;
        let half = self.f(0.5);
        let center = self.b.f_add(self.t.f32, None, pixel, half)?;
        self.cast_u(center)
    }

    fn ipa(&mut self, i: &Insn) -> R {''')

    replace_once(draw, '    use super::depth_state;', '''    use super::{depth_state, reg, sample_grid, scissor_bounds, viewport};

    #[test]
    fn multisample_coordinates_cover_the_physical_color_and_depth_grid() {
        let mut regs = [0u32; 0x1000];
        for (index, value) in [(0, 640.0f32), (1, -360.0), (3, 640.0), (4, 360.0)] {
            regs[reg::VIEWPORT_SCALE + index] = value.to_bits();
        }
        regs[reg::SCISSOR + 1] = 1 | 1280 << 16;
        regs[reg::SCISSOR + 2] = 2 | 720 << 16;
        let extent = (2560, 1440);
        let normal = viewport(&regs, extent);
        assert_eq!((normal.x, normal.y, normal.width, normal.height), (0.0, 720.0, 1280.0, -720.0));
        assert_eq!(scissor_bounds(&regs, extent), [1, 2, 1280, 720]);
        regs[reg::ANTI_ALIAS] = 2;
        let aa = viewport(&regs, extent);
        assert_eq!((aa.x, aa.y, aa.width, aa.height), (0.0, 1440.0, 2560.0, -1440.0));
        assert_eq!(scissor_bounds(&regs, extent), [2, 4, 2560, 1440]);
        regs[reg::ANTI_ALIAS] = 5;
        assert_eq!(sample_grid(&regs), [2, 1]);
        assert_eq!(scissor_bounds(&regs, extent), [2, 2, 2560, 720]);
    }''')

    test = root / 'crates/maxwell/tests/translate.rs'
    replace_once(test, '#[test]\nfn straight_line_fragment_shader()', '''#[test]
fn fragment_position_uses_logical_centers_on_a_multisample_grid() {
    use rspirv::{dr::{Loader, Operand}, spirv::Op};
    let floor_count = |spirv: &[u32]| {
        let mut loader = Loader::new();
        rspirv::binary::parse_words(spirv, &mut loader).unwrap();
        loader.module().all_inst_iter().filter(|i| {
            i.class.opcode == Op::ExtInst && i.operands.get(1) == Some(&Operand::LiteralExtInstInteger(8))
        }).count()
    };
    let code = program(fragment_header(1), &[ipa(0, 0x70, 0xff), ipa(1, 0x74, 0xff), EXIT]);
    let options = options(Stage::Fragment);
    let ordinary = translate(&code, &options, &kirikae_maxwell::NoEnv).unwrap();
    assert_eq!(floor_count(&ordinary.spirv), 0);
    let msaa = Options { fragment_sample_grid: [2, 2], ..options };
    let shader = translate(&code, &msaa, &kirikae_maxwell::NoEnv).unwrap();
    assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
    assert_eq!(floor_count(&shader.spirv), 2);
    validate(&shader.spirv);
}

#[test]
fn straight_line_fragment_shader()''')
