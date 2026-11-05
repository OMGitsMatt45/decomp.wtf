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
