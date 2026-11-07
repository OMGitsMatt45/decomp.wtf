
fn readonly_storage_qualification() {
    let mem = GuestMemory::new().unwrap();
    mem.map(0x100000, 0x300000).unwrap();
    let gpu = Gpu::default();
    gpu.map(0x1_0000_0000, 0x100000, 0x300000);
    const SHARED_BUFFER: u64 = 0x1_000e_6000;
    const SHARED_CPU: u64 = 0x1e6000;
    const RED: [f32; 4] = [1.0, 0.0, 0.0, 1.0];
    const GREEN: [f32; 4] = [0.0, 1.0, 0.0, 1.0];
    const BLUE: [f32; 4] = [0.0, 0.0, 1.0, 1.0];
    let cache_on = std::env::var_os("KIRIKAE_READONLY_SSBO_CACHE").is_some_and(|v| v == "1")
        && std::env::var_os("KIRIKAE_NO_BUFFER_CACHE").is_none();
    let ld_attr = |rd: u64, attr: u64| 0xefd8_0000_0000_0000 | 3 << 47 | 0xff << 39 | attr << 20 | PT | 0xff << 8 | rd;
    let st_attr = |rd: u64, attr: u64| 0xeff0_0000_0000_0000 | 3 << 47 | 0xff << 39 | attr << 20 | PT | 0xff << 8 | rd;
    let storage_address = |offset: u64| 0x4c98_0000_0000_0000 | (offset / 4) << 20 | PT | 8;
    let vs = [ld_attr(0, 0x80), st_attr(0, 0x70), storage_address(0x110),
        0xeed0_0000_0000_0000 | 6 << 48 | PT | 8 << 8 | 4, st_attr(4, 0x80), EXIT];
    let fs_read = [ld_attr(0, 0x80), EXIT];
    let fs_write = [ld_attr(0, 0x80), storage_address(0x510),
        mov(4, GREEN[0]), mov(5, GREEN[1]), mov(6, GREEN[2]), mov(7, GREEN[3]),
        0xeed8_0000_0000_0000 | 6 << 48 | PT | 8 << 8 | 4, EXIT];
    assert!(mem.write(0x1e2000, &shader(false, &vs)));
    assert!(mem.write(0x1e3000, &shader(true, &fs_read)));
    assert!(mem.write(0x1e4000, &shader(true, &fs_write)));
    let vertices = [-0.6f32, -0.6, 0.5, 1.0, 0.6, -0.6, 0.5, 1.0, 0.0, 0.6, 0.5, 1.0];
    let bytes = |words: &[f32]| words.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>();
    assert!(mem.write(0x130000, &bytes(&vertices)));
    let bind_storage = |va: u64| {
        let mut constants = vec![0; 0x600];
        for offset in [0x110, 0x510] {
            constants[offset..offset+8].copy_from_slice(&va.to_le_bytes());
            constants[offset+8..offset+12].copy_from_slice(&16u32.to_le_bytes());
        }
        assert!(mem.write(0x1e5000, &constants));
    };
    let draw = |cp: &mut Vec<u32>, target: u32, writer: bool| {
        method(cp, 0, &[CLASS_3D]);
        method(cp, 0x200, &[1, target, 128 * 4, 96, 0xd5, 1 << 12]);
        method(cp, 0x487, &[1]);
        method(cp, 0x680, &[0x1111]);
        method(cp, 0x380, &[0]);
        method(cp, 0x360, &[1f32.to_bits(), 0, 1f32.to_bits(), 1f32.to_bits()]);
        method(cp, 0x674, &[0x3c]);
        if writer {
            // One covered fragment writes the alias, with no competing stores.
            method(cp, 0x380, &[1, 64 | 65 << 16, 48 | 49 << 16]);
        }
        method(cp, 0x4eb, &[0]);
        method(cp, 0x646, &[0]);
        method(cp, 0x280, &[64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits(), 64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits()]);
        address(cp, 0x582, 0x1_0000_0000);
        method(cp, 0x810, &[1, 0xe2000]);
        method(cp, 0x850, &[1, if writer { 0xe4000 } else { 0xe3000 }]);
        method(cp, 0x8e0, &[0x600]);
        address(cp, 0x8e1, 0x1_000e_5000);
        method(cp, 0x904, &[1]);
        method(cp, 0x924, &[1]);
        method(cp, 0x458, &[1 << 21 | 7 << 27]);
        method(cp, 0x620, &[0]);
        method(cp, 0x700, &[16]);
        address(cp, 0x701, 0x1_0003_0000);
        address(cp, 0x7c0, 0x1_0003_002f);
        method(cp, 0x35d, &[0]);
        method(cp, 0x586, &[4]);
        method(cp, 0x35e, &[3]);
        method(cp, 0x585, &[0]);
    };
    let submit = |cp: &[u32]| {
        assert!(mem.write(0x300000, &cp.iter().flat_map(|word| word.to_le_bytes()).collect::<Vec<_>>()));
        gpu.submit(&mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
    };
    let center = |cpu: u64| {
        let pixels = gpu.read_pixels(cpu, 128, 96).expect("readonly SSBO target");
        assert_eq!(pixels[0] & 0xffffff, 0xff00ff, "clear outside geometry");
        pixels[48 * 128 + 64] & 0xffffff
    };
    let stats = || gpu.render_stats().unwrap_or_default();
    let one_draw = || {
        let mut cp = Vec::new();
        draw(&mut cp, 0x100000, false);
        submit(&cp);
        center(0x200000)
    };
    bind_storage(SHARED_BUFFER);
    assert!(mem.write(SHARED_CPU, &bytes(&RED)));
    #[cfg(debug_assertions)]
    let resident_before = stats().readonly_storage_resident;
    for _ in 0..4 { assert_eq!(one_draw(), 0xff0000); }
    #[cfg(debug_assertions)]
    assert_eq!(stats().readonly_storage_resident > resident_before, cache_on);

    // The same descriptor points to fresh bytes at the next batch boundary.
    assert!(mem.write(SHARED_CPU, &bytes(&GREEN)));
    #[cfg(debug_assertions)]
    let resident_before = stats().readonly_storage_resident;
    assert_eq!(one_draw(), 0x00ff00, "guest CPU update of a resident SSBO");
    #[cfg(debug_assertions)]
    assert_eq!(stats().readonly_storage_resident, resident_before);
    for _ in 0..3 { assert_eq!(one_draw(), 0x00ff00); }

    // Write through an actual CP inline packet between two draws in one submit.
    let mut cp = Vec::new();
    draw(&mut cp, 0x100000, false);
    method(&mut cp, 0x60, &[16, 1, (SHARED_BUFFER >> 32) as u32, SHARED_BUFFER as u32]);
    method(&mut cp, 0x6c, &[0]);
    for word in BLUE.map(f32::to_bits) { method(&mut cp, 0x6d, &[word]); }
    draw(&mut cp, 0x110000, false);
    let batches = stats().batches;
    submit(&cp);
    assert_eq!(stats().batches - batches, 1, "the CP write stayed in the draw batch");
    assert_eq!(center(0x200000), 0x00ff00);
    if cache_on { assert_eq!(center(0x210000), 0x0000ff, "CP write invalidation in a single batch"); }
    assert_eq!(mem.read(SHARED_CPU, 16).unwrap(), bytes(&BLUE));
    for _ in 0..4 { assert_eq!(one_draw(), 0x0000ff); }

    // Both shader stages bind the same guest address. The writer must use the
    // shared ring, and the next readonly draw must observe its pending bytes.
    let before = stats();
    let mut cp = Vec::new();
    draw(&mut cp, 0x100000, true);
    draw(&mut cp, 0x110000, false);
    submit(&cp);
    assert_eq!(stats().batches - before.batches, 1, "the GPU writer and reader shared one batch");
    assert_eq!(center(0x200000), 0x0000ff, "vertex read before fragment write");
    assert_eq!(center(0x210000), 0x00ff00, "pending GPU write visible to readonly draw");
    let after = stats();
    #[cfg(debug_assertions)]
    assert_eq!(after.readonly_storage_resident, before.readonly_storage_resident);
    assert_eq!(mem.read(SHARED_CPU, 16).unwrap(), bytes(&GREEN));

    let before = stats();
    for missing in [0, 0x9_0000_0000] {
        bind_storage(missing);
        assert_eq!(one_draw(), 0, "missing storage must retain zero-fill fallback");
    }
    let after = stats();
    #[cfg(debug_assertions)]
    assert_eq!(after.readonly_storage_resident, before.readonly_storage_resident);
    assert_eq!(after.skipped, before.skipped);
    gpu.shutdown();
    eprintln!("qualified readonly storage cache={cache_on}, guest and CP writes, VS/FS aliases, pending GPU writes and zero-fill");
}
