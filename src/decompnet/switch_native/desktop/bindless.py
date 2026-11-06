"""Expose statically identified Maxwell TEX.B handles to the host renderer."""


def apply(root):
    from .patches import replace_once

    translate = root / 'crates/maxwell/src/translate.rs'
    replace_once(translate, 'pub trait Env {', '''pub trait Env {
    fn texture_use_kind(&self, usage: &TextureUse) -> Kind {
        self.texture_kind(usage.slot, usage.handle)
    }
''')
    replace_once(translate, 'pub struct TextureUse {\n    pub kind: Kind,', '''pub struct TextureUse {
    pub kind: Kind,
    pub or_cbuf: Option<(u32, u32)>,''')
    replace_once(translate, '#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub struct ImageUse {', '''impl TextureUse {
    pub fn handle_word<E>(&self, default_slot: u32, mut read: impl FnMut(u32, u32) -> Result<u32, E>) -> Result<u32, E> {
        let word = read(self.slot.unwrap_or(default_slot), self.handle * 4)?;
        match self.or_cbuf {
            Some((slot, offset)) => Ok(word | read(slot, offset)?),
            None => Ok(word),
        }
    }
}

#[derive(Clone, Copy)]
struct TextureHandle {
    slot: Option<u32>,
    word: u32,
    or_cbuf: Option<(u32, u32)>,
}

impl TextureHandle {
    fn bound(word: u32) -> Self {
        Self { slot: None, word, or_cbuf: None }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ImageUse {''')
    replace_once(translate, '    textures: Vec<(TextureUse, Word)>,', '''    textures: Vec<(TextureUse, Word)>,
    texture_handles: [Option<TextureHandle>; 256],
    inherited_texture_handles: [Option<TextureHandle>; 256],
    written_texture_regs: [bool; 256],
    used_inherited_texture_regs: [bool; 256],''')
    replace_once(translate, '            textures: Vec::new(),', '''            textures: Vec::new(),
            texture_handles: [None; 256],
            inherited_texture_handles: [None; 256],
            written_texture_regs: [false; 256],
            used_inherited_texture_regs: [false; 256],''')
    replace_once(translate, '            self.b.store(self.regs[reg as usize], v, None, [])?;', '''            self.texture_handles[reg as usize] = None;
            self.written_texture_regs[reg as usize] = true;
            self.b.store(self.regs[reg as usize], v, None, [])?;''')
    replace_once(translate, '            for (_, block) in program.blocks() {', '''            for (_, block) in program.blocks() {
                self.texture_handles.fill(None);''')
    # Only a unique fallthrough may provide the initial value for an optional self-loop.
    replace_once(translate, '        let blocks = program.blocks();', '''        let blocks = program.blocks();
        let mut inherit_texture_handles = vec![false; blocks.len()];
        if !program.insns.values().any(|i| matches!(i.name(), "brx" | "sync" | "brk") || (i.name() == "bra" && i.bit(5))) {
            let branch_entries: std::collections::BTreeSet<_> = blocks.iter().flat_map(|(leader, insns)| {
                insns.iter().filter(|(_, i)| i.name() == "bra")
                    .map(|(pc, i)| i.branch_target(*pc)).filter(move |target| target != leader)
            }).collect();
            for (k, pair) in blocks.windows(2).enumerate() {
                let leader = pair[1].0;
                let (pc, last) = pair[0].1.last().unwrap();
                inherit_texture_handles[k + 1] = cfg::next(*pc) == leader
                    && !matches!(last.name(), "bra" | "exit") && !branch_entries.contains(&leader);
            }
        }''')
    for merge in ('skip', 'sw_merge'):
        replace_once(translate, f'self.block(pc_var, {merge}, insns)?;',
                     f'self.block(pc_var, {merge}, insns, inherit_texture_handles[k])?;')
    replace_once(translate, '    fn block(&mut self, pc_var: Word, merge: Word, insns: &[(u32, Insn)]) -> R {', '''    fn block(&mut self, pc_var: Word, merge: Word, insns: &[(u32, Insn)], inherit_texture_handles: bool) -> R {
        let previous = std::mem::replace(&mut self.texture_handles, [None; 256]);
        self.inherited_texture_handles = if inherit_texture_handles { previous } else { [None; 256] };
        self.written_texture_regs.fill(false);
        self.used_inherited_texture_regs.fill(false);''')
    replace_once(translate, '        if !self.ended {\n            let fall = self.block_number(cfg::next(last));', '''        // A write after a sample could reach that sample on the next loop iteration.
        if self.used_inherited_texture_regs.iter().zip(&self.written_texture_regs).any(|(&used, &written)| used && written) {
            self.unsupported.push("tex (bindless)");
        }
        if !self.ended {
            let fall = self.block_number(cfg::next(last));''')
    replace_once(translate, '''            "mov" => {
                let v = self.src_b(i)?;
                self.set(i.rd(), v)
            }''', '''            "mov" => {
                let v = self.src_b(i)?;
                self.set(i.rd(), v)?;
                if i.rd() != RZ && i.form() == Form::Cbuf && i.guard() == (PT, false) {
                    let (slot, offset) = i.cbuf();
                    self.texture_handles[i.rd() as usize] = Some(TextureHandle { slot: Some(slot), word: offset / 4, or_cbuf: None });
                }
                Ok(())
            }''')
    replace_once(translate, '''                self.set(i.rd(), v)
            }
            "lop3" => {''', '''                let handle = if i.name() == "lop" && i.form() == Form::Cbuf && op == 1
                    && !inv_a && !inv_b && i.guard() == (PT, false)
                {
                    self.texture_handles[i.ra() as usize].filter(|src| src.or_cbuf.is_none())
                        .map(|src| TextureHandle { or_cbuf: Some(i.cbuf()), ..src })
                } else {
                    None
                };
                self.set(i.rd(), v)?;
                if i.rd() != RZ {
                    self.texture_handles[i.rd() as usize] = handle;
                }
                Ok(())
            }
            "lop3" => {''')
    replace_once(translate, '''        let kind = if shadow { Kind::Float } else { self.env.texture_kind(slot, handle) };
        let key = TextureUse { slot, handle, dim, array, shadow, binding: 0, kind };''', '''        let mut key = TextureUse { slot, handle, or_cbuf, dim, array, shadow, binding: 0, kind: Kind::Float };
        if !shadow {
            key.kind = self.env.texture_use_kind(&key);
        }
        let kind = key.kind;''')
    replace_once(translate, '''    fn texture(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool, shadow: bool) -> (Word, Word, Word, Word, Kind) {
        let mut key''', '''    fn texture(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool, shadow: bool) -> (Word, Word, Word, Word, Kind) {
        self.texture_from(TextureHandle { slot, word: handle, or_cbuf: None }, dim, array, shadow)
    }

    fn texture_from(&mut self, handle: TextureHandle, dim: TexDim, array: bool, shadow: bool) -> (Word, Word, Word, Word, Kind) {
        let TextureHandle { slot, word: handle, or_cbuf } = handle;
        let mut key''')
    replace_once(translate, 'self.textures.iter().find(|(u, _)| u.slot == slot && u.handle == handle && u.dim == dim && u.array == array && u.shadow == shadow)',
                 'self.textures.iter().find(|(u, _)| (TextureUse { binding: 0, ..*u }) == key)')
    replace_once(translate, 'fn sample(&mut self, handle: u32, dim: TexDim,', 'fn sample(&mut self, handle: TextureHandle, dim: TexDim,')
    replace_once(translate, 'self.texture(None, handle, dim, array, shadow);', 'self.texture_from(handle, dim, array, shadow);')
    replace_once(translate, 'self.sample(handle, dim, array, shadow, coords, layer, lod, dref, None)',
                 'self.sample(TextureHandle::bound(handle), dim, array, shadow, coords, layer, lod, dref, None)')
    replace_once(translate, '''        if i.op.value != 0xc038000000000000 {
            self.unsupported.push("tex (bindless)");
            return Ok(());
        }
        let handle = i.bits(36, 13) as u32;''', '''        let bindless = i.op.value == 0xdeb8000000000000;
        let handle = if bindless {
            let reg = i.rb() as usize;
            let handle = self.texture_handles[reg].or_else(|| {
                if self.written_texture_regs[reg] {
                    return None;
                }
                let handle = self.inherited_texture_handles[reg]?;
                self.used_inherited_texture_regs[reg] = true;
                Some(handle)
            });
            let Some(handle) = handle else {
                self.unsupported.push("tex (bindless)");
                return Ok(());
            };
            if i.bit(35) {
                self.unsupported.push("tex (bindless NDV)");
                return Ok(());
            }
            handle
        } else {
            TextureHandle::bound(i.bits(36, 13) as u32)
        };''')
    replace_once(translate, '''        let mut reg_b = i.rb();
        let mut take_b = |t: &mut Self| -> R<Word> {
            let r = reg_b;
            if reg_b != RZ {
                reg_b += 1;
            }
            t.r(r)
        };
        let lod = match i.bits(55, 3) {''', '''        let mut reg_b = if bindless { i.rb().saturating_add(1) } else { i.rb() };
        let mut take_b = |t: &mut Self| -> R<Word> {
            let r = reg_b;
            if reg_b != RZ {
                reg_b += 1;
            }
            t.r(r)
        };
        let lod = match i.bits(if bindless { 37 } else { 55 }, 3) {''')
    replace_once(translate, 'let offset = if i.bit(54) { Some(take_b(self)?) } else { None };',
                 'let offset = if i.bit(if bindless { 36 } else { 54 }) { Some(take_b(self)?) } else { None };')

    vulkan = root / 'crates/rt/src/gpu/vulkan'
    replace_once(vulkan / 'pipeline.rs', '''            fn texture_kind(&self, slot: Option<u32>, handle: u32) -> Kind {
                let Some(word) = self.cbuf(slot.unwrap_or(self.default_slot), handle * 4) else { return Kind::Float };''',
                 '''            fn texture_use_kind(&self, usage: &kirikae_maxwell::TextureUse) -> Kind {
                let Ok(word) = usage.handle_word(self.default_slot, |slot, offset| self.cbuf(slot, offset).ok_or(())) else { return Kind::Float };''')
    replace_once(vulkan / 'pipeline.rs', 'kirikae_maxwell::Env::texture_kind(&env, t.slot, t.handle)',
                 'kirikae_maxwell::Env::texture_use_kind(&env, t)')
    replace_once(vulkan / 'descriptors.rs', 'self.texture(gpu, mem, regs, cbufs, t.slot, t.handle, t.dim, t.array, t.shadow)',
                 'self.texture(gpu, mem, regs, cbufs, t)')
    textures = vulkan / 'textures.rs'
    replace_once(textures, 'use kirikae_maxwell::TexDim;', 'use kirikae_maxwell::{TexDim, TextureUse};')
    replace_once(textures, '''    #[allow(clippy::too_many_arguments)]
    pub(super) fn texture(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: [Option<(u64, u32)>; CB_SLOTS], slot: Option<u32>, handle: u32, dim: TexDim, array: bool, shadow: bool) -> Result<(vk::ImageView, vk::Sampler), String> {
        let mut lap = self.clock_start();
        let slot = slot.unwrap_or(regs[reg::BINDLESS_TEXTURE] & 0x1f);
        let (cb, cb_size) = cbufs[slot as usize].ok_or_else(|| format!("texture constant buffer {slot} not bound"))?;
        if handle * 4 + 4 > cb_size {
            return Err("texture handle outside its constant buffer".into());
        }
        let word = gpu.bytes(mem, cb + handle as u64 * 4, 4).ok_or("texture handle unreadable")?;
        let word = u32::from_le_bytes(word.try_into().unwrap());''', '''    pub(super) fn texture(&mut self, gpu: &Gpu, mem: &GuestMemory, regs: &[u32], cbufs: [Option<(u64, u32)>; CB_SLOTS], usage: TextureUse) -> Result<(vk::ImageView, vk::Sampler), String> {
        let mut lap = self.clock_start();
        let TextureUse { handle, dim, array, shadow, .. } = usage;
        let word = usage.handle_word(regs[reg::BINDLESS_TEXTURE] & 0x1f, |slot, offset| {
            let (cb, cb_size) = cbufs.get(slot as usize).copied().flatten().ok_or_else(|| format!("texture constant buffer {slot} not bound"))?;
            if offset + 4 > cb_size {
                return Err("texture handle outside its constant buffer".into());
            }
            let word = gpu.bytes(mem, cb + offset as u64, 4).ok_or("texture handle unreadable")?;
            Ok::<_, String>(u32::from_le_bytes(word.try_into().unwrap()))
        })?;''')

    test = root / 'crates/maxwell/tests/translate.rs'
    replace_once(test, '#[test]\nfn straight_line_fragment_shader()', '''#[test]
fn tex_b_uses_cbuf_handles_and_decodes_its_lod_field() {
    use kirikae_maxwell::{Env, Kind, TextureUse};

    struct Textures;
    impl Env for Textures {
        fn texture_use_kind(&self, usage: &TextureUse) -> Kind {
            let word = usage.handle_word(0, |slot, offset| match (slot, offset) {
                (2, 0x168) => Ok(0x0010_0033),
                (2, 0x568) => Ok(0x5500_0080),
                _ => Err(()),
            }).unwrap();
            assert_eq!(word, if usage.or_cbuf.is_some() { 0x5510_00b3 } else { 0x0010_0033 });
            Kind::Float
        }
    }

    // The retail instruction forms are MOV R3,c[2][0x168], LOP.OR R3,R3,c[2][0x568], and TEX.B.
    const MOV: u64 = 0x4c98_0788_05a7_0003;
    const OR: u64 = 0x4c47_0208_15a7_0303;
    const TEX_B: u64 = 0xdeb8_0003_a037_0c0c;
    let code = program(fragment_header(1), &[MOV, TEX_B, OR, mov32i(4, 1.5f32.to_bits()), TEX_B | 3 << 37, EXIT]);
    let shader = translate(&code, &options(Stage::Fragment), &Textures).unwrap();
    assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
    assert_eq!(shader.textures.len(), 2);
    assert_eq!((shader.textures[0].slot, shader.textures[0].handle, shader.textures[0].or_cbuf), (Some(2), 0x168 / 4, None));
    assert_eq!((shader.textures[1].slot, shader.textures[1].handle, shader.textures[1].or_cbuf), (Some(2), 0x168 / 4, Some((2, 0x568))));
    let spirv = disassemble(&shader.spirv);
    assert!(spirv.contains("OpImageSampleImplicitLod"), "{spirv}");
    assert!(spirv.contains("OpImageSampleExplicitLod"), "{spirv}");
    validate(&shader.spirv);
}

#[test]
fn tex_b_rejects_a_clobbered_or_predicated_handle() {
    const MOV: u64 = 0x4c98_0788_05a7_0003;
    const OR: u64 = 0x4c47_0208_15a7_0303;
    const TEX_B: u64 = 0xdeb8_0003_a037_0c0c;
    for insns in [[MOV, OR, mov32i(3, 0), TEX_B, EXIT], [MOV, OR & !PT, NOP, TEX_B, EXIT]] {
        let code = program(fragment_header(1), &insns);
        let shader = translate(&code, &options(Stage::Fragment), &kirikae_maxwell::NoEnv).unwrap();
        assert_eq!(shader.unsupported, ["tex (bindless)"]);
        assert!(shader.textures.is_empty());
    }
}

#[test]
fn tex_b_keeps_only_a_loop_invariant_fallthrough_handle() {
    const MOV: u64 = 0x4c98_0788_05a7_0003;
    const OR: u64 = 0x4c47_0208_15a7_0303;
    const TEX_B: u64 = 0xdeb8_0003_a037_0c0c;
    let back_edge = bra(-0x18, 0);
    let run = |first_branch, after_sample| {
        let code = program(fragment_header(1), &[first_branch, MOV, OR, TEX_B, after_sample, back_edge, EXIT]);
        translate(&code, &options(Stage::Fragment), &kirikae_maxwell::NoEnv).unwrap()
    };

    // The entry branch can skip the loop entirely. Its only way in is after MOV and LOP.OR.
    let skip_loop = bra(0x38, 0);
    let invariant = run(skip_loop, NOP);
    assert!(invariant.unsupported.is_empty(), "{:?}", invariant.unsupported);
    assert_eq!(invariant.textures.len(), 1);
    assert_eq!(invariant.textures[0].or_cbuf, Some((2, 0x568)));
    validate(&invariant.spirv);

    let clobbered = run(skip_loop, mov32i(3, 0));
    assert_eq!(clobbered.unsupported, ["tex (bindless)"]);
    let bypass_definition = run(bra(0x18, 0), NOP);
    assert_eq!(bypass_definition.unsupported, ["tex (bindless)"]);
}

#[test]
fn straight_line_fragment_shader()''')
