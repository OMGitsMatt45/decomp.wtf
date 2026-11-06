"""Checked extensions to the pinned Maxwell and Vulkan sources."""
import re


def integer_textures(root):
    from .patches import replace_once

    translate = root / 'crates/maxwell/src/translate.rs'
    replace_once(translate, 'pub trait Env {', '''pub trait Env {
    fn texture_kind(&self, _slot: Option<u32>, _handle: u32) -> Kind {
        Kind::Float
    }
''')
    replace_once(translate, "    opts: &'a Options,\n    header: Header,", "    opts: &'a Options,\n    env: &'a dyn Env,\n    header: Header,")
    replace_once(translate, 'Translator::new(opts, header)', 'Translator::new(opts, header, env)')
    replace_once(translate, "fn new(opts: &'a Options, header: Header) -> Self {", "fn new(opts: &'a Options, header: Header, env: &'a dyn Env) -> Self {")
    replace_once(translate, '            opts,\n            header,', '            opts,\n            env,\n            header,')
    replace_once(translate, 'pub struct TextureUse {', 'pub struct TextureUse {\n    pub kind: Kind,')
    replace_once(translate, '''fn texture(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool, shadow: bool) -> (Word, Word, Word, Word) {
        let key = TextureUse { slot, handle, dim, array, shadow, binding: 0 };
        let image_ty = self.image_type(dim, array, shadow);''', '''fn texture(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool, shadow: bool) -> (Word, Word, Word, Word, Kind) {
        let kind = if shadow { Kind::Float } else { self.env.texture_kind(slot, handle) };
        let key = TextureUse { slot, handle, dim, array, shadow, binding: 0, kind };
        let image_ty = self.image_type(dim, array, shadow, kind);''')
    replace_once(translate, 'return (var, var + 1, image_ty, sampled_ty);', 'return (var, var + 1, image_ty, sampled_ty, kind);')
    replace_once(translate, '(image, sampler, image_ty, sampled_ty)\n    }', '(image, sampler, image_ty, sampled_ty, kind)\n    }')
    replace_once(translate, 'let (image_var, _, image_ty, _) = self.texture(None, handle, TexDim::D2, false, false);',
                 'let (image_var, _, image_ty, _, _) = self.texture(None, handle, TexDim::D2, false, false);')
    replace_once(translate, 'let (image_var, sampler_var, image_ty, sampled_ty) = self.texture(slot, handle, dim, array, false);',
                 'let (image_var, sampler_var, image_ty, sampled_ty, _) = self.texture(slot, handle, dim, array, false);')
    replace_once(translate, 'fn image_type(&mut self, dim: TexDim, array: bool, shadow: bool) -> Word {', '''fn texture_types(&self, kind: Kind) -> (Word, Word) {
        match kind {
            Kind::Float => (self.t.f32, self.t.v4f),
            Kind::Sint => (self.t.i32, self.t.v4i),
            Kind::Uint => (self.t.u32, self.t.v4u),
        }
    }

    fn texture_component(&mut self, vector: Word, kind: Kind, index: u32) -> R<Word> {
        let (scalar, _) = self.texture_types(kind);
        let value = self.b.composite_extract(scalar, None, vector, [index])?;
        if kind == Kind::Uint { Ok(value) } else { self.cast_u(value) }
    }

    fn image_type(&mut self, dim: TexDim, array: bool, shadow: bool, kind: Kind) -> Word {''')
    replace_once(translate, 'self.b.type_image(self.t.f32, d, shadow as u32, array as u32, 0, 1, ImageFormat::Unknown, None)',
                 'let (scalar, _) = self.texture_types(kind);\n        self.b.type_image(scalar, d, shadow as u32, array as u32, 0, 1, ImageFormat::Unknown, None)')
    for tail in ('shadow', 'dref.is_some()'):
        replace_once(translate,
                     'let (image_var, sampler_var, image_ty, sampled_ty) = self.texture(None, handle, dim, array, ' + tail + ');',
                     'let (image_var, sampler_var, image_ty, sampled_ty, kind) = self.texture(None, handle, dim, array, ' + tail + ');\n        let (_, vector) = self.texture_types(kind);')
    replace_once(translate, 'image_sample_explicit_lod(self.t.v4f, None, image, coord, ops.unwrap(), extra)',
                 'image_sample_explicit_lod(vector, None, image, coord, ops.unwrap(), extra)')
    replace_once(translate, 'image_sample_implicit_lod(self.t.v4f, None, image, coord, ops, extra)',
                 'image_sample_implicit_lod(vector, None, image, coord, ops, extra)')
    replace_once(translate, 'image_gather(self.t.v4f, None, image, coord, c, ops, extra)',
                 'image_gather(vector, None, image, coord, c, ops, extra)')
    replace_once(translate, 'let (image_var, _, image_ty, _) = self.texture(None, handle, dim, array, false);',
                 'let (image_var, _, image_ty, _, kind) = self.texture(None, handle, dim, array, false);\n        let (_, vector) = self.texture_types(kind);')
    replace_once(translate, 'image_fetch(self.t.v4f, None, img, coord, Some(ImageOperands::LOD)',
                 'image_fetch(vector, None, img, coord, Some(ImageOperands::LOD)')
    for indent, next_line in ((16, '            }\n            out'), (12, '        }\n        Ok(out)\n    }\n\n    fn gather_offset'),
                              (12, '        }\n        Ok(out)\n    }\n\n    fn texs_results')):
        space = ' ' * indent
        replace_once(translate, space + 'let f = self.b.composite_extract(self.t.f32, None, v, [c as u32])?;\n'
                     + space + '*o = self.cast_u(f)?;\n' + next_line,
                     space + '*o = self.texture_component(v, kind, c as u32)?;\n' + next_line)

    gpu = root / 'crates/rt/src/gpu'
    formats = gpu / 'formats.rs'
    replace_once(formats, 'pub struct TexFormat {', 'pub struct TexFormat {\n    pub kind: Kind,')
    replace_once(formats, 'TexFormat { vk, block_bytes: bytes, block_w: 1, block_h: 1, astc: false }',
                 'TexFormat { vk, block_bytes: bytes, block_w: 1, block_h: 1, astc: false, kind: Kind::Float }')
    replace_once(formats, 'const fn block(vk:', '''const fn integer(vk: vk::Format, bytes: u32, kind: Kind) -> TexFormat {
    TexFormat { kind, ..plain(vk, bytes) }
}

const fn block(vk:''')
    replace_once(formats, 'TexFormat { vk, block_bytes: bytes, block_w: 4, block_h: 4, astc: false }',
                 'TexFormat { vk, block_bytes: bytes, block_w: 4, block_h: 4, astc: false, kind: Kind::Float }')
    replace_once(formats, 'block_h: h, astc: true }', 'block_h: h, astc: true, kind: Kind::Float }')
    code = formats.read_text()
    for name, kind, count in (('SINT', 'Sint', 9), ('UINT', 'Uint', 10)):
        pattern = rf'(\b{name}\) => )plain\((F::\w+), (\d+)\),'
        code, n = re.subn(pattern, rf'\1integer(\2, \3, Kind::{kind}),', code)
        if n != count:
            raise ValueError('Switch integer texture format patch no longer applies')
    formats.write_text(code, encoding='utf-8', newline='\n')

    pipeline = gpu / 'vulkan/pipeline.rs'
    replace_once(pipeline, '''        if let Some(s) = self.shaders.get(&key) {
            return Ok(s.clone());
        }
''', '')
    replace_once(pipeline, '''        struct Env<'a> {
            gpu: &'a Gpu,
            mem: &'a GuestMemory,
            cbufs: [Option<(u64, u32)>; CB_SLOTS],
        }''', '''        struct Env<'a> {
            gpu: &'a Gpu,
            mem: &'a GuestMemory,
            cbufs: [Option<(u64, u32)>; CB_SLOTS],
            default_slot: u32,
            header_pool: u64,
        }''')
    replace_once(pipeline, "        impl kirikae_maxwell::Env for Env<'_> {", """        impl kirikae_maxwell::Env for Env<'_> {
            fn texture_kind(&self, slot: Option<u32>, handle: u32) -> Kind {
                let Some(word) = self.cbuf(slot.unwrap_or(self.default_slot), handle * 4) else { return Kind::Float };
                let address = self.header_pool + (word & 0xfffff) as u64 * 32;
                let Some(words) = self.gpu.bytes(self.mem, address, 32).and_then(crate::gpu::tic::words) else { return Kind::Float };
                let header = crate::gpu::tic::texture_header(&words);
                formats::texture(header.components, header.data_type, header.srgb).map_or(Kind::Float, |format| format.kind)
            }
""")
    # Keep all typed variants alive so cached pipelines retain their shader modules.
    replace_once(pipeline, '        let env = Env { gpu, mem, cbufs };', '''        let env = Env { gpu, mem, cbufs, default_slot: regs[reg::BINDLESS_TEXTURE] & 0x1f,
            header_pool: crate::gpu::threed::address(regs, reg::TEX_HEADER_POOL) };''')
    code = pipeline.read_text()
    env = code[code.index("        struct Env<'a> {"):code.index('        let start = std::time::Instant::now();', code.index('        let env = Env {'))]
    replace_once(pipeline, env, '')
    replace_once(pipeline, '        let mut size = 0x10000u64;', env + '''        if let Some(shader) = self.shaders.get(&key).and_then(|variants| variants.iter().find(|variant| {
            variant.shader.textures.iter().all(|t| t.shadow || t.kind == kirikae_maxwell::Env::texture_kind(&env, t.slot, t.handle))
        })) {
            return Ok(shader.clone());
        }
        let mut size = 0x10000u64;''')
    replace_once(pipeline, '        self.shaders.insert(key, s.clone());', '        self.shaders.entry(key).or_default().push(s.clone());')
    replace_once(gpu / 'vulkan/mod.rs', 'shaders: HashMap<ShaderKey, Arc<ShaderModule>>,',
                 'shaders: HashMap<ShaderKey, Vec<Arc<ShaderModule>>>,')
    replace_once(gpu / 'vulkan/mod.rs', 'for s in self.shaders.values() {', 'for s in self.shaders.values().flatten() {')

    test = root / 'crates/maxwell/tests/translate.rs'
    replace_once(test, '#[test]\nfn straight_line_fragment_shader()', '''#[test]
fn texel_fetch_uses_the_bound_texture_numeric_type() {
    use kirikae_maxwell::{Env, Kind};
    use rspirv::{dr::Loader, spirv::Op};

    struct Texture(Kind);
    impl Env for Texture {
        fn texture_kind(&self, slot: Option<u32>, handle: u32) -> Kind {
            assert_eq!((slot, handle), (None, 8));
            self.0
        }
    }

    // TLDS R0, R2, R0, R1, 8, 2D, followed by EXIT.
    let fetch = 0xd200_0000_0000_0000 | 2 << 53 | 4 << 50 | 8 << 36 | 2 << 28 | 1 << 20 | PT;
    let code = program(fragment_header(1), &[mov32i(0, 0), mov32i(1, 0), fetch, EXIT]);
    for kind in [Kind::Float, Kind::Sint, Kind::Uint] {
        let shader = translate(&code, &options(Stage::Fragment), &Texture(kind)).unwrap();
        assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
        assert_eq!(shader.textures[0].kind, kind);
        let mut loader = Loader::new();
        rspirv::binary::parse_words(&shader.spirv, &mut loader).unwrap();
        let module = loader.module();
        let types = &module.types_global_values;
        let image = types.iter().find(|i| i.class.opcode == Op::TypeImage).unwrap();
        let scalar = image.operands[0].unwrap_id_ref();
        let scalar = types.iter().find(|i| i.result_id == Some(scalar)).unwrap();
        match kind {
            Kind::Float => assert_eq!(scalar.class.opcode, Op::TypeFloat),
            Kind::Sint | Kind::Uint => {
                assert_eq!(scalar.class.opcode, Op::TypeInt);
                assert_eq!(scalar.operands[1].unwrap_literal_bit32(), (kind == Kind::Sint) as u32);
            }
        }
        assert!(module.all_inst_iter().any(|i| i.class.opcode == Op::ImageFetch));
        validate(&shader.spirv);
    }
}

#[test]
fn straight_line_fragment_shader()''')


def maxwell_integer_saturation(root):
    from .patches import replace_once

    translate = root / 'crates/maxwell/src/translate.rs'
    replace_once(translate, '''    fn i2i(&mut self, i: &Insn) -> R {
        let b = self.src_b(i)?;
        let v = self.int_source(b, i.bits(10, 2), i.bit(13), i.bits(41, 2))?;
''', '''    fn i2i(&mut self, i: &Insn) -> R {
        let b = self.src_b(i)?;
        let v = self.int_source(b, i.bits(10, 2), i.bit(13), i.bits(41, 2))?;
        if i.bit(50) {
            let saturated = self.saturating_i2i(i, v)?;
            return self.set(i.rd(), saturated);
        }
''')
    replace_once(translate, '    fn pack_half(&mut self, f: Word) -> R<Word> {', '''    fn saturating_i2i(&mut self, i: &Insn, value: Word) -> R<Word> {
        let u = self.t.u32;
        let width = 8 << i.bits(8, 2).min(2);
        let signed_dest = i.bit(12);
        let upper = u32::MAX >> (32 - width + u32::from(signed_dest));
        let upper = self.u(upper);
        if !i.bit(13) && !i.bit(45) {
            return self.ext(u, glsl::UMIN, &[value, upper]);
        }

        // Keep the sign separate so source modifiers can represent both
        // abs(INT_MIN) and negated unsigned words before clamping.
        let zero = self.u(0);
        let false_ = self.b.constant_false(self.t.bool);
        let (magnitude, mut negative) = if i.bit(13) {
            let source = self.cast_i(value)?;
            let signed_zero = self.cast_i(zero)?;
            let sign = self.b.s_less_than(self.t.bool, None, source, signed_zero)?;
            let negated = self.b.i_sub(u, None, zero, value)?;
            let magnitude = self.b.select(u, None, sign, negated, value)?;
            (magnitude, if i.bit(49) { false_ } else { sign })
        } else {
            (value, false_)
        };
        if i.bit(45) {
            negative = self.b.logical_not(self.t.bool, None, negative)?;
        }
        let positive = self.ext(u, glsl::UMIN, &[magnitude, upper])?;
        let negative_value = if signed_dest {
            let limit = self.u(1 << (width - 1));
            let clamped = self.ext(u, glsl::UMIN, &[magnitude, limit])?;
            self.b.i_sub(u, None, zero, clamped)?
        } else {
            zero
        };
        Ok(self.b.select(u, None, negative, negative_value, positive)?)
    }

    fn pack_half(&mut self, f: Word) -> R<Word> {''')

    test = root / 'crates/maxwell/tests/translate.rs'
    replace_once(test, '#[test]\nfn straight_line_fragment_shader()', '''fn integer_conversion_result(spirv: &[u32]) -> u32 {
    use rspirv::{dr::Loader, spirv::Op};
    use std::collections::HashMap;

    // Evaluate the straight-line scalar integer instructions in this fixture.
    let mut loader = Loader::new();
    rspirv::binary::parse_words(spirv, &mut loader).unwrap();
    let module = loader.module();
    let mut values = HashMap::<u32, u32>::new();
    let mut variables = HashMap::<u32, u32>::new();
    for insn in &module.types_global_values {
        let value = match insn.class.opcode {
            Op::Constant => insn.operands[0].unwrap_literal_bit32(),
            Op::ConstantFalse => 0,
            Op::ConstantTrue => 1,
            _ => continue,
        };
        values.insert(insn.result_id.unwrap(), value);
    }
    for insn in &module.functions[0].blocks[0].instructions {
        let id = |n: usize| insn.operands[n].unwrap_id_ref();
        let v = |n| values[&id(n)];
        let value = match insn.class.opcode {
            Op::Variable => continue,
            Op::Store => { variables.insert(id(0), v(1)); continue; }
            Op::Load => variables[&id(0)],
            Op::Bitcast => v(0),
            Op::BitwiseAnd => v(0) & v(1),
            Op::ISub => v(0).wrapping_sub(v(1)),
            Op::SLessThan => u32::from((v(0) as i32) < (v(1) as i32)),
            Op::LogicalNot => u32::from(v(0) == 0),
            Op::Select => if v(0) != 0 { v(1) } else { v(2) },
            Op::BitFieldUExtract => (v(0) >> v(1)) & (u32::MAX >> (32 - v(2))),
            Op::BitFieldSExtract => (((v(0) << (32 - v(1) - v(2))) as i32) >> (32 - v(2))) as u32,
            Op::ExtInst if insn.operands[1].unwrap_literal_ext_inst_integer() == 38 => v(2).min(v(3)),
            Op::CompositeConstruct => return v(0), // Render target R.
            opcode => panic!("Unexpected instruction in integer conversion fixture: {opcode:?}"),
        };
        values.insert(insn.result_id.unwrap(), value);
    }
    panic!("No render target output in integer conversion fixture");
}

#[test]
fn i2i_sat_clamps_to_the_typed_destination_range() {
    const U8: u64 = 0;
    const U16: u64 = 1;
    const U32: u64 = 2;
    const S8: u64 = 4;
    const S16: u64 = 5;
    const S32: u64 = 6;
    const SAT: u64 = 1 << 50;
    const ABS: u64 = 1 << 49;
    const NEG: u64 = 1 << 45;
    let cases = [
        (U8, U32, 256, 0, 0),
        (U8, U32, 256, SAT, 255),
        (U8, U32, 7, SAT, 7),
        (U8, S32, -1i32 as u32, SAT, 0),
        (S8, S32, 128, SAT, 127),
        (S8, S32, -129i32 as u32, SAT, -128i32 as u32),
        (S8, S8, 0xfe, SAT, -2i32 as u32),
        (U16, U32, 65536, SAT, 65535),
        (U16, U16, 0xffff_0001, SAT, 1),
        (S16, U32, 65535, SAT, 32767),
        (S16, S32, -32769i32 as u32, SAT, -32768i32 as u32),
        (S16, S16, 0xfffe, SAT, -2i32 as u32),
        (S32, U32, u32::MAX, SAT, i32::MAX as u32),
        (U32, S32, i32::MIN as u32, SAT, 0),
        (U32, U32, u32::MAX, SAT, u32::MAX),
        (S32, S32, i32::MIN as u32, SAT | NEG, i32::MAX as u32),
        (U32, S32, i32::MIN as u32, SAT | ABS, 0x8000_0000),
        (S8, U32, 255, SAT | NEG, -128i32 as u32),
    ];
    for (dest, src, value, flags, expected) in cases {
        let i2i = 0x5ce0_0000_0000_0000 | flags | PT | 1 << 20
            | (dest & 3) << 8 | (src & 3) << 10 | (dest >> 2) << 12 | (src >> 2) << 13;
        let code = program(fragment_header(1), &[mov32i(1, value), i2i, EXIT]);
        let shader = translate(&code, &options(Stage::Fragment), &kirikae_maxwell::NoEnv).unwrap();
        assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
        validate(&shader.spirv);
        assert_eq!(integer_conversion_result(&shader.spirv), expected, "I2I {i2i:016x}, {value:08x}");
    }
}

#[test]
fn straight_line_fragment_shader()''')
