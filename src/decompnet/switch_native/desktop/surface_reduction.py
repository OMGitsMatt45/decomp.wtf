"""Translate typed Maxwell fragment image reductions without changing the donor."""


def apply(root):
    from .patches import replace_once

    draw = root / 'crates/rt/src/gpu/vulkan/draw.rs'
    replace_once(draw, '        scratch.targets = targets;', '''        if fs.as_ref().is_some_and(|s| s.shader.images.iter().any(|image| image.atomic_u32)) {
            self.end_rendering();
        }
        scratch.targets = targets;''')

    translate = root / 'crates/maxwell/src/translate.rs'
    replace_once(translate, '    pub array: bool,\n    pub binding: u32,',
                 '    pub array: bool,\n    pub atomic_u32: bool,\n    pub binding: u32,')
    replace_once(translate, '            "sust" => self.sust(pc, i),',
                 '            "sust" => self.sust(pc, i),\n            "sured" => self.sured(i),')
    for end in ('"hsetp2", "csetp", "dsetp"];', '"hsetp2", "csetp"];'):
        old = ('        const NO_RD: &[&str] = &["st", "stg", "sts", "stl", "sust", "red", '
               '"exit", "bra", "brx", "sync", "ssy", "pbk", "brk", "kil", "depbar", "bar", '
               '"membar", "nop", "isetp", "fsetp", "psetp", ' + end)
        replace_once(translate, old, old.replace('"sust",', '"sust", "sured",'))
    replace_once(translate,
                 'fn storage_image(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool)',
                 'fn storage_image(&mut self, slot: Option<u32>, handle: u32, dim: TexDim, array: bool, atomic_u32: bool)')
    replace_once(translate, '        if !self.storage_images {', '        if !atomic_u32 && !self.storage_images {')
    replace_once(translate, '''        let image_ty = self.b.type_image(self.t.f32, d, 0, array as u32, 0, 2, ImageFormat::Unknown, None);
        if let Some(&(_, var)) = self.images.iter().find(|(u, _)| u.slot == slot && u.handle == handle && u.dim == dim && u.array == array) {''', '''        let (sampled_type, format) = if atomic_u32 { (self.t.u32, ImageFormat::R32ui) } else { (self.t.f32, ImageFormat::Unknown) };
        let image_ty = self.b.type_image(sampled_type, d, 0, array as u32, 0, 2, format, None);
        if let Some(&(_, var)) = self.images.iter().find(|(u, _)| u.slot == slot && u.handle == handle && u.dim == dim && u.array == array && u.atomic_u32 == atomic_u32) {''')
    replace_once(translate, '''        self.b.decorate(var, Decoration::NonReadable, []);
        self.images.push((ImageUse { slot, handle, dim, array, binding }, var));''', '''        if !atomic_u32 {
            self.b.decorate(var, Decoration::NonReadable, []);
        }
        self.images.push((ImageUse { slot, handle, dim, array, atomic_u32, binding }, var));''')
    replace_once(translate, '        let (var, image_ty) = self.storage_image(slot, handle, dim, array);',
                 '        let (var, image_ty) = self.storage_image(slot, handle, dim, array, false);')
    replace_once(translate, '    fn image_type(&mut self, dim: TexDim, array: bool, shadow: bool, kind: Kind) -> Word {', '''    fn sured(&mut self, i: &Insn) -> R {
        // SURED.D.T2D.MAX.IGN on a U32 image with a statically bound handle.
        if self.opts.stage != Stage::Fragment || !i.bit(52) || i.bit(51)
            || i.bits(49, 2) != 0 || i.bits(33, 3) != 3 || i.bits(24, 3) != 2 || i.bits(20, 4) != 0
        {
            self.unsupported.push("sured (mode)");
            return Ok(());
        }
        let Some(TextureHandle { slot, word, or_cbuf: None }) = self.texture_handles[i.rc() as usize] else {
            self.unsupported.push("sured (bindless)");
            return Ok(());
        };
        let (var, image_ty) = self.storage_image(slot, word, TexDim::D2, false, true);
        let u = self.t.u32;
        let xy = self.t.v2u;
        let x = self.r(i.ra())?;
        let y = self.r(i.ra().saturating_add(1))?;
        let value = self.r(i.rd())?;
        let coords = self.b.composite_construct(xy, None, [x, y])?;

        // IGN discards out-of-range texels, including negative coordinates.
        let image = self.b.load(image_ty, None, var, None, [])?;
        let size = self.b.image_query_size(xy, None, image)?;
        let width = self.b.composite_extract(u, None, size, [0])?;
        let height = self.b.composite_extract(u, None, size, [1])?;
        let in_x = self.b.u_less_than(self.t.bool, None, x, width)?;
        let in_y = self.b.u_less_than(self.t.bool, None, y, height)?;
        let valid = self.b.logical_and(self.t.bool, None, in_x, in_y)?;
        let (reduce, merge) = (self.b.id(), self.b.id());
        self.b.selection_merge(merge, SelectionControl::NONE)?;
        self.b.branch_conditional(valid, reduce, merge, [])?;
        self.b.begin_block(Some(reduce))?;
        let ptr_ty = self.b.type_pointer(None, StorageClass::Image, u);
        let zero = self.u(0);
        let device = self.u(1);
        let ptr = self.b.image_texel_pointer(ptr_ty, None, var, coords, zero)?;
        self.b.atomic_u_max(u, None, ptr, device, zero, value)?;
        self.b.branch(merge)?;
        self.b.begin_block(Some(merge))?;
        Ok(())
    }

    fn image_type(&mut self, dim: TexDim, array: bool, shadow: bool, kind: Kind) -> Word {''')

    vulkan = root / 'crates/rt/src/gpu/vulkan'
    module = vulkan / 'mod.rs'
    replace_once(module, '    depth_bias_clamp: bool,',
                 '    depth_bias_clamp: bool,\n    fragment_image_atomics: bool,')
    replace_once(module, '        let features = vk::PhysicalDeviceFeatures::default()', '''        let r32_uint = unsafe { instance.get_physical_device_format_properties(physical, vk::Format::R32_UINT) };
        let fragment_image_atomics = supported.fragment_stores_and_atomics == vk::TRUE
            && r32_uint.optimal_tiling_features.contains(vk::FormatFeatureFlags::STORAGE_IMAGE | vk::FormatFeatureFlags::STORAGE_IMAGE_ATOMIC);
        let features = vk::PhysicalDeviceFeatures::default()
            .fragment_stores_and_atomics(fragment_image_atomics)''')
    replace_once(module, '            depth_bias_clamp: supported.depth_bias_clamp == vk::TRUE,',
                 '            depth_bias_clamp: supported.depth_bias_clamp == vk::TRUE,\n            fragment_image_atomics,')
    replace_once(module, '            vk::DescriptorPoolSize { ty: vk::DescriptorType::STORAGE_BUFFER, descriptor_count: 16384 },',
                 '            vk::DescriptorPoolSize { ty: vk::DescriptorType::STORAGE_BUFFER, descriptor_count: 16384 },\n'
                 '            vk::DescriptorPoolSize { ty: vk::DescriptorType::STORAGE_IMAGE, descriptor_count: 16384 },')

    images = vulkan / 'images.rs'
    replace_once(images, '        let slot = image.slot.unwrap_or(regs[reg::BINDLESS_TEXTURE] & 0x1f);', '''        if image.atomic_u32 && !self.fragment_image_atomics {
            return Err("Vulkan device does not support fragment R32_UINT storage image atomics".into());
        }
        let slot = image.slot.unwrap_or(regs[reg::BINDLESS_TEXTURE] & 0x1f);''')
    replace_once(images, '        let cpu = gpu.translate(header.address).ok_or("image not mapped")?;', '''        if image.atomic_u32 && format.vk != vk::Format::R32_UINT {
            return Err(format!("R32_UINT storage image atomic bound to {:?}", format.vk));
        }
        let cpu = gpu.translate(header.address).ok_or("image not mapped")?;''')
    replace_once(images, '        let level = if header.texture_type == 7 { 0 } else { header.min_level };', '''        if image.atomic_u32 && view_format != vk::Format::R32_UINT {
            return Err(format!("R32_UINT storage image atomic resolved to {view_format:?}"));
        }
        let level = if header.texture_type == 7 { 0 } else { header.min_level };''')

    descriptors = vulkan / 'descriptors.rs'
    replace_once(descriptors, '''            let view = match self.storage_image(gpu, mem, regs, cbufs, &i) {
                Ok(v) => v,
                Err(why) => {''', '''            let view = match self.storage_image(gpu, mem, regs, cbufs, &i) {
                Ok(v) => v,
                Err(why) if i.atomic_u32 => return Err(why),
                Err(why) => {''')
    replace_once(descriptors, '            out.push(Descriptor::StorageImage(i.binding, view));', '''            if i.atomic_u32 {
                self.draw_wrote_storage = true;
            }
            out.push(Descriptor::StorageImage(i.binding, view));''')

    tests = root / 'crates/maxwell/tests/translate.rs'
    with tests.open('a', encoding='utf-8', newline='\n') as out:
        out.write('''
#[test]
fn typed_surface_max_uses_a_guarded_uint_texel_atomic() {
    use kirikae_maxwell::{ImageUse, TexDim};

    let mov_handle = 0x4c98_0000_0000_0000 | 2 << 34 | (0x128 / 4) << 20 | PT | 1;
    let reduction = 0xeb40_0000_0000_0000 | 1 << 52 | 1 << 39 | 3 << 33 | 2 << 24 | PT | 10 << 8;
    let opts = options(Stage::Fragment);
    let code = program(fragment_header(0), &[mov_handle, reduction, EXIT]);
    let shader = translate(&code, &opts, &kirikae_maxwell::NoEnv).unwrap();
    assert!(shader.unsupported.is_empty(), "{:?}", shader.unsupported);
    assert_eq!(shader.images, [ImageUse {
        slot: Some(2), handle: 74, dim: TexDim::D2, array: false, atomic_u32: true, binding: opts.image_binding,
    }]);
    let text = disassemble(&shader.spirv);
    assert!(text.lines().any(|line| line.contains("OpTypeImage") && line.contains("R32ui")), "{text}");
    assert!(!text.contains("NonReadable"), "{text}");
    let query = text.find("OpImageQuerySize").expect("image bounds");
    let guarded = text[query..].find("OpBranchConditional").expect("guarded atomic") + query;
    let ptr = text.find("OpImageTexelPointer").expect("typed texel pointer");
    let atomic = text.find("OpAtomicUMax").expect("unsigned maximum");
    assert!(query < guarded && guarded < ptr && ptr < atomic, "{text}");

    let other_mode = program(fragment_header(0), &[mov_handle, reduction ^ (1 << 24), EXIT]);
    let unsupported = translate(&other_mode, &opts, &kirikae_maxwell::NoEnv).unwrap();
    assert_eq!(unsupported.unsupported, ["sured (mode)"]);
    assert!(unsupported.images.is_empty());

    let unknown_handle = program(fragment_header(0), &[reduction, EXIT]);
    let unsupported = translate(&unknown_handle, &opts, &kirikae_maxwell::NoEnv).unwrap();
    assert_eq!(unsupported.unsupported, ["sured (bindless)"]);
    assert!(unsupported.images.is_empty());
}
''')
