
fn derived_feedback() {
    let mem = GuestMemory::new().unwrap();
    mem.map(0x100000, 0x300000).unwrap();
    let gpu = Gpu::default();
    gpu.map(0x1_0000_0000, 0x100000, 0x300000);
    const VERTEX_MACRO: [u32; 18] = [
        0x0346c215, 0x00000401, 0x00000301, 0x0014d310, 0x00d74061,
        0x0002d807, 0x01438061, 0x01618021, 0x00000841, 0x00d78021,
        0x00002041, 0x01614071, 0xffffdb11, 0x00004211, 0xfffe5817,
        0xd0808912, 0x014380f1, 0x00000011,
    ];
    let words = |data: &[u32]| data.iter().flat_map(|word| word.to_le_bytes()).collect::<Vec<_>>();
    let ald = |rd: u64, at: u64, count: u64| {
        0xefd8_0000_0000_0000 | (count - 1) << 47 | 0xff << 39 | at << 20 | PT | 0xff << 8 | rd
    };
    let imm = |op: u64, rd: u64, ra: u64, value: f32| {
        op | (value.to_bits() as u64) << 20 | PT | ra << 8 | rd
    };
    let vs = [ald(0, 0x80, 4), ald(4, 0x2f8, 1),
        0x5cb8_0000_0000_0000 | 2 << 10 | 2 << 8 | PT | 4 << 20 | 4,
        imm(0x1e00_0000_0000_0000, 4, 4, 0.5),
        imm(0x0800_0000_0000_0000, 4, 4, -0.5),
        0x5c58_0000_0000_0000 | 4 << 20 | PT,
        0xeff0_0000_0000_0000 | 3 << 47 | 0xff << 39 | 0x70 << 20 | PT | 0xff << 8, EXIT];
    assert!(mem.write(0x1e8000, &shader(false, &vs)));
    let vertices = [-0.2f32, -0.4, 0.5, 1.0, 0.2, -0.4, 0.5, 1.0, 0.0, 0.4, 0.5, 1.0];
    assert!(mem.write(0x130000, &vertices.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));

    let mut differences = Vec::new();
    for twin in [false, true] {
        let target = if twin { 0x1_0015_0000u64 } else { 0x1_0014_0000u64 };
        let (target_format, texture_width, shader_offset) = if twin { (0xe5, 128, 0xea000) } else { (0xd5, 64, 0xe9000) };
        let components = if twin { 0x0f | 7 << 7 } else { 0x08 | 2 << 7 | 2 << 10 | 2 << 13 | 2 << 16 };
        let swizzle = 2 << 19 | 3 << 22 | 4 << 25 | 5 << 28;
        let tic = [components | swizzle, target as u32, (target >> 32) as u32 | 1 << 21,
            16, (texture_width - 1) | 1 << 23, 95, 0, 0];
        let compare_less = 1 << 9 | 1 << 10;
        let tsc = [if twin { compare_less } else { 0 }, 0, 0, 0, 0, 0, 0, 0];
        assert!(mem.write(0x180000, &words(&tic)));
        assert!(mem.write(0x180040, &words(&tsc)));
        assert!(mem.write(0x180060, &words(&[0])));
        let sample = |kind: u64, second: u64| {
            0xd800_0000_0000_0000 | kind << 53 | 4 << 50 | 2 << 28 | second << 20 | PT | 4 << 8
        };
        let fs = if twin {
            // Read the first triangle through the R32 color image's depth twin.
            // The initial depth .25 compares false against .5. Its inverted
            // result writes 1, which must compare true in the later instances.
            vec![mov(4, 0.25), mov(5, 0.5), mov(6, 0.5), sample(4, 6),
                imm(0x1e00_0000_0000_0000, 0, 0, -1.0),
                imm(0x0800_0000_0000_0000, 0, 0, 1.0), EXIT]
        } else {
            // The 64-pixel crop reads x32 from the 128-pixel target. The first
            // instance adds .25 red, and later instances must sample that edit.
            vec![mov(4, 0.5), mov(5, 0.5), sample(1, 5),
                imm(0x0800_0000_0000_0000, 0, 0, 0.25), EXIT]
        };
        assert!(mem.write(0x100000 + u64::from(shader_offset), &shader(true, &fs)));
        let mut reference = None;
        for macro_draw in [false, true] {
            let mut cp = Vec::new();
            method(&mut cp, 0, &[CLASS_3D]);
            address(&mut cp, 0x200, target);
            method(&mut cp, 0x202, &[128 * 4, 96, target_format, 1 << 12]);
            method(&mut cp, 0x487, &[1]); method(&mut cp, 0x680, &[0x1111]);
            method(&mut cp, 0x380, &[0]);
            method(&mut cp, 0x360, &if twin { [0.25f32, 0.0, 0.0, 1.0] } else { [0.0, 1.0, 0.0, 1.0] }.map(f32::to_bits));
            method(&mut cp, 0x674, &[0x3c]);
            method(&mut cp, 0x4eb, &[0]); method(&mut cp, 0x646, &[0]);
            method(&mut cp, 0x280, &[64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits(), 64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits()]);
            address(&mut cp, 0x582, 0x1_0000_0000);
            method(&mut cp, 0x810, &[1, 0xe8000]); method(&mut cp, 0x850, &[1, shader_offset]);
            address(&mut cp, 0x55d, 0x1_0008_0000); address(&mut cp, 0x557, 0x1_0008_0040);
            method(&mut cp, 0x8e0, &[32]); address(&mut cp, 0x8e1, 0x1_0008_0060); method(&mut cp, 0x924, &[1]);
            method(&mut cp, 0x458, &[1 << 21 | 7 << 27]); method(&mut cp, 0x620, &[0]);
            method(&mut cp, 0x700, &[16]); address(&mut cp, 0x701, 0x1_0003_0000); address(&mut cp, 0x7c0, 0x1_0003_002f);
            method(&mut cp, 0x35d, &[0]);
            if macro_draw {
                method(&mut cp, 0x45, &[0]);
                for word in VERTEX_MACRO { method(&mut cp, 0x46, &[word]); }
                method(&mut cp, 0x47, &[0]); method(&mut cp, 0x48, &[0]); method(&mut cp, 0xd1b, &[u32::MAX]);
                method(&mut cp, 0xe00, &[4]);
                for arg in [3, 3, 0, 0] { method(&mut cp, 0xe01, &[arg]); }
                method(&mut cp, 0x100, &[0]);
            } else {
                for begin in [4, 4 | 1 << 26, 4 | 1 << 26] {
                    method(&mut cp, 0x586, &[begin]); method(&mut cp, 0x35e, &[3]); method(&mut cp, 0x585, &[0]);
                }
            }
            let before = gpu.render_stats().unwrap_or_default();
            assert!(mem.write(0x300000, &words(&cp)));
            gpu.submit(&mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
            let pixels = gpu.read_pixels(gpu.translate(target).unwrap(), 128, 96).expect("derived feedback readback");
            let centers = [32, 64, 96].map(|x| pixels[48 * 128 + x] & 0xffffff);
            let expected = if twin { [0xffffff, 0, 0] } else { [0x40ff00, 0x80ff00, 0x80ff00] };
            let after = gpu.render_stats().unwrap();
            assert_eq!(after.skipped, before.skipped);
            assert_eq!(after.draws - before.draws, 3);
            if let Some(reference) = &reference {
                let batches = after.instance_batches - before.instance_batches;
                if centers != expected || &pixels != reference || batches != 0 {
                    differences.push((twin, centers, expected, batches));
                }
            } else {
                assert_eq!(centers, expected, "expanded derived feedback twin={twin}");
                reference = Some(pixels);
            }
        }
    }
    assert!(differences.is_empty(), "derived feedback differences (twin, actual, expected, batches): {differences:x?}");
    gpu.shutdown();
    eprintln!("kirikae: crop and depth-twin feedback matched three separate draws");
}
