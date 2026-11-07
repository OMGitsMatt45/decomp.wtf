
fn produce_instance_stream(gpu: &Gpu, mem: &GuestMemory, partial: bool) {
    use kirikae_rt::gpu::compute::{QMD_CBUFS, Qmd};

    let (cb_offset, output, values): (u64, u64, &[f32]) = if partial {
        (0xf2000, 0x1_000c_000c, &[0.75, 0.25, 0.5])
    } else {
        (0xf0000, 0x1_000c_0000, &[0.0, 0.125, 0.375, 0.25, 0.5, 0.75])
    };
    let mut constants = [0; 0x270];
    constants[0x260..0x268].copy_from_slice(&output.to_le_bytes());
    constants[0x268..0x26c].copy_from_slice(&(values.len() as u32 * 4).to_le_bytes());
    assert!(mem.write(0x100000 + cb_offset, &constants));

    // One compute invocation loads the SSBO address from cbuf0 and stores
    // distinct green values. The graphics test consumes this pending range.
    let mut instructions = vec![0x4c98_0000_0000_0000 | (0x260 / 4) << 20 | PT | 8];
    for (record, &value) in values.iter().enumerate() {
        instructions.push(mov(0, value));
        instructions.push(0xeed8_0000_0000_0000 | 4 << 48 | (record as u64 * 4) << 20 | PT | 8 << 8);
    }
    instructions.push(EXIT);
    let compute = shader(false, &instructions);
    assert!(mem.write(0x101000 + cb_offset, &compute[0x50..]));
    let mut cbufs = [None; QMD_CBUFS];
    cbufs[0] = Some((0x1_0000_0000 + cb_offset, constants.len() as u32));
    let qmd = Qmd { program: 0, grid: [1; 3], block: [1; 3], shared: 0, local: 0, cbufs };
    assert_eq!(gpu.with_renderer(|renderer| {
        renderer.dispatch(gpu, mem, &[0; 0x1000], &qmd, 0x1_0000_1000 + cb_offset)
    }), Some(true), "instance stream compute producer");
}

fn instance_batches(gpu: &Gpu, mem: &GuestMemory) {
    let native_enabled = std::env::var_os("KIRIKAE_MME_INSTANCES").is_none_or(|value| value != "0");
    const CODE: [u32; 31] = [
        0x00000601, 0x00000501, 0x0346c215, 0x017dc061, 0x01118451,
        0x00002041, 0x05434021, 0x00002331, 0x00001841, 0x0638c021,
        0x01900041, 0x00155510, 0x00002041, 0x0002e807, 0x00001841,
        0x01618021, 0x00000841, 0x017e0021, 0x00003041, 0x01614071,
        0xffffed11, 0x00004211, 0xfffe6817, 0xd0808912, 0x01118071,
        0x01434071, 0x01438071, 0x0638c021, 0x01900041, 0x000000c1, 0x00000041,
    ];
    const INDEXED_MACRO_30: [u32; 23] = [
        0x00000501,0x0346c215,0x00000401,0x017dc061,0x01118351,
        0x00001841,0x05434021,0x00151410,0x00001a31,0x0002e007,
        0x00001041,0x01618021,0x00000841,0x017e0021,0x00002841,
        0x01614071,0xffffe411,0x00004211,0xfffe6017,0xd0808912,
        0x01118071,0x014340f1,0x01438071,
    ];
    const VERTEX_MACRO_27: [u32; 18] = [
        0x0346c215,0x00000401,0x00000301,0x0014d310,0x00d74061,
        0x0002d807,0x01438061,0x01618021,0x00000841,0x00d78021,
        0x00002041,0x01614071,0xffffdb11,0x00004211,0xfffe5817,
        0xd0808912,0x014380f1,0x00000011,
    ];
    let ald = |rd: u64, at: u64, count: u64| 0xefd8_0000_0000_0000u64 | (count - 1) << 47 | 0xff << 39 | at << 20 | PT | 0xff << 8 | rd;
    let ast = |rd: u64, at: u64| 0xeff0_0000_0000_0000u64 | 3 << 47 | 0xff << 39 | at << 20 | PT | 0xff << 8 | rd;
    let float_imm = |op: u64, rd: u64, ra: u64, value: f32| op | (value.to_bits() as u64) << 20 | PT | ra << 8 | rd;
    // InstanceIndex 3,4,5 produces three distinct horizontal positions and red
    // intensities. The stream variants also read a per-instance green value.
    let instance_streams = std::env::var("KIRIKAE_INSTANCE_VERTEX_STREAMS").is_ok_and(|value| value == "1");
    let pending_streams = std::env::var("KIRIKAE_INSTANCE_PENDING_STREAMS").is_ok_and(|value| value == "1");
    for (macro_index, code, indexed) in [(0, CODE.as_slice(), true), (1, VERTEX_MACRO_27.as_slice(), false), (2, INDEXED_MACRO_30.as_slice(), true)] {
        for variant in 0..9 {
            let gpu_stream = matches!(variant, 7 | 8);
            let instanced = matches!(variant, 1 | 4 | 5 | 6 | 7 | 8);
            let storage = matches!(variant, 2 | 3);
            let writable = variant == 3;
            let divisor = if variant == 4 { 2 } else { 1 };
            let mut vs = vec![ald(0, 0x80, 4), ald(4, 0x2f8, 1),
                0x5cb8_0000_0000_0000 | 2 << 10 | 2 << 8 | PT | 4 << 20 | 4,
                float_imm(0x0800_0000_0000_0000, 4, 4, -2.0),
                float_imm(0x1e00_0000_0000_0000, 4, 4, 0.25),
                float_imm(0x1e00_0000_0000_0000, 5, 4, 2.0),
                float_imm(0x0800_0000_0000_0000, 5, 5, -1.0),
                0x5c58_0000_0000_0000 | 5 << 20 | PT,
                ast(0, 0x70), mov(5, 0.0), mov(6, 0.0), mov(7, 1.0)];
            if instanced { vs.push(ald(5, 0x90, 1)); }
            if storage {
                // Reload the integer InstanceIndex, derive an address from the
                // real cbuf0 storage descriptor and fetch this instance's green.
                vs.extend([ald(10, 0x2f8, 1),
                    0x4c98_0000_0000_0000 | (0x110 / 4) << 20 | PT | 8,
                    0x5c18_0000_0000_0000 | 2 << 39 | 8 << 20 | 10 << 8 | PT | 9,
                    0xeed0_0000_0000_0000 | 4 << 48 | PT | 9 << 8 | 5]);
            }
            vs.extend([ast(4, 0x80), EXIT]);
            let vertex_offset = 0xd0000 + variant * 0x1000;
            assert!(mem.write(0x100000 + vertex_offset, &shader(false, &vs)));
            let fragment_offset = if writable { 0xb2000 } else { 0xb0000 };
            let mut fs = vec![ald(0, 0x80, 4)];
            if writable {
                fs.extend([0x4c98_0000_0000_0000 | (0x510 / 4) << 20 | PT | 8,
                    0xeed8_0000_0000_0000 | 4 << 48 | PT | 8 << 8]);
            }
            fs.push(EXIT);
            assert!(mem.write(0x100000 + fragment_offset, &shader(true, &fs)));
            let mut vertices = vec![0f32; 9 * 4];
            vertices.extend([-0.18, -0.30, 0.5, 1.0, 0.18, -0.30, 0.5, 1.0, 0.0, 0.30, 0.5, 1.0]);
            assert!(mem.write(0x130000, &vertices.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
            assert!(mem.write(0x190000, &[99, 0, 99, 0, 2, 0, 3, 0, 4, 0]));
            let green = [0f32, 0.125, 0.375, 0.25, 0.5, 0.75];
            assert!(mem.write(0x1c0000, &green.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
            let stream_va = if variant == 6 {
                // The final record is mapped through a distinct physical range.
                // One-record draws remain valid but the whole prefix is not contiguous.
                let va = 0x3_1000_0000;
                gpu.map(va, 0x1c0000, 20);
                gpu.map(va + 20, 0x1c2000, 4);
                assert!(mem.write(0x1c2000, &green[5].to_le_bytes()));
                va
            } else {
                0x1_000c_0000
            };
            let mut cbuf = vec![0; 0x600];
            for (offset, address, size) in [(0x110, 0x1_000c_0000u64, 24u32), (0x510, 0x1_000c_1000u64, 16u32)] {
                cbuf[offset..offset+8].copy_from_slice(&address.to_le_bytes());
                cbuf[offset+8..offset+12].copy_from_slice(&size.to_le_bytes());
            }
            assert!(mem.write(0x1e0000, &cbuf));
            assert!(mem.write(0x1c1000, &[0; 16]));
            let mut images = Vec::new();
            for batched in [false, true] {
                let before = gpu.render_stats().unwrap();
                let mut cp = Vec::new();
                method(&mut cp, 0, &[CLASS_3D]);
                method(&mut cp, 0x4eb, &[0]); method(&mut cp, 0x646, &[0]);
                method(&mut cp, 0x280, &[64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits(), 64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits()]);
                method(&mut cp, 0x810, &[1, vertex_offset as u32]); method(&mut cp, 0x850, &[1, fragment_offset as u32]);
                method(&mut cp, 0x8e0, &[0x600]); address(&mut cp, 0x8e1, 0x1_000e_0000);
                method(&mut cp, 0x904, &[1]); method(&mut cp, 0x924, &[1]);
                method(&mut cp, 0x458, &[1 << 21 | 7 << 27, 1 | 0x12 << 21 | 7 << 27]);
                method(&mut cp, 0x700, &[16]); address(&mut cp, 0x701, 0x1_0003_0000); address(&mut cp, 0x7c0, 0x1_0003_00bf);
                method(&mut cp, 0x704, &[4]);
                address(&mut cp, 0x705, stream_va);
                method(&mut cp, 0x707, &[divisor]);
                method(&mut cp, 0x621, &[u32::from(instanced)]);
                let stream_limit = stream_va + if variant == 5 { 19 } else { 23 };
                address(&mut cp, 0x7c2, stream_limit);
                address(&mut cp, 0x5f2, 0x1_0009_0000); method(&mut cp, 0x5f6, &[1, 2]); method(&mut cp, 0x591, &[0, 0]);
                method(&mut cp, 0x35d, &[9]); method(&mut cp, 0x50d, &[7]); method(&mut cp, 0x674, &[0x3c]);
                // Establish a nonzero InstanceIndex before the exact loop.
                method(&mut cp, 0x586, &[4]); method(&mut cp, 0x585, &[0]);
                for _ in 0..3 { method(&mut cp, 0x586, &[4 | 1 << 26]); method(&mut cp, 0x585, &[0]); }
                if batched {
                    method(&mut cp, 0x45, &[0]);
                    for &word in code { method(&mut cp, 0x46, &[word]); }
                    method(&mut cp, 0x47, &[macro_index]); method(&mut cp, 0x48, &[0]); method(&mut cp, 0xd1b, &[u32::MAX]);
                    method(&mut cp, 0xe00 + 2 * macro_index, &[4 | 2 << 26]);
                    let params = if indexed { vec![3, 3, 2, 7, 11] } else { vec![3, 3, 9, 11] };
                    for parameter in params { method(&mut cp, 0xe01 + 2 * macro_index, &[parameter]); }
                    method(&mut cp, 0x100, &[0]);
                } else {
                    for begin in [4 | 2 << 26, 4 | 1 << 26, 4 | 1 << 26] {
                        method(&mut cp, 0x586, &[begin]); method(&mut cp, if indexed { 0x5f8 } else { 0x35e }, &[3]); method(&mut cp, 0x585, &[0]);
                    }
                    method(&mut cp, 0x50d, &[0]);
                }
                if gpu_stream {
                    assert!(mem.write(0x1c0000, &[0; 32]));
                    produce_instance_stream(gpu, mem, false);
                    if variant == 8 {
                        // A newer write covers the consumed records but not the
                        // complete prefix. It must override the earlier full write.
                        produce_instance_stream(gpu, mem, true);
                    }
                    assert_eq!(mem.read(0x1c0000, 24).unwrap(), vec![0; 24]);
                }
                assert!(mem.write(0x300000, &cp.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
                gpu.submit(mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
                let pixels = gpu.read_pixels(0x200000, 128, 96).expect("instance batch readback");
                let after = gpu.render_stats().unwrap();
                assert_eq!(after.skipped, before.skipped);
                assert_eq!(after.draws - before.draws, 3);
                let native = batched && native_enabled;
                let native_pending = native && variant == 7 && instance_streams && pending_streams;
                let native_stream = (native && variant == 1 && instance_streams) || native_pending;
                let native_batch = native && ((!instanced && !writable) || native_stream);
                assert_eq!(after.instance_batches - before.instance_batches, u64::from(native_batch),
                    "MME fixture {macro_index}, shader variant {variant}");
                assert_eq!(after.instance_stream_batches - before.instance_stream_batches, u64::from(native_stream));
                assert_eq!(after.instance_pending_batches - before.instance_pending_batches, u64::from(native_pending));
                for (slot, x) in [32usize, 64, 96].into_iter().enumerate() {
                    let pixel = pixels[48 * 128 + x];
                    let intensity = [64i32, 128, 191][slot];
                    assert!(((pixel >> 16 & 255) as i32 - intensity).abs() <= 1, "instance color/position {slot}: {pixel:06x}");
                    let expected_green = if variant == 8 {
                        [191, 64, 128][slot]
                    } else if instanced {
                        (green[(slot + 3) / divisor as usize] * 255.0).round() as i32
                    } else if storage {
                        intensity
                    } else {
                        0
                    };
                    assert!(((pixel >> 8 & 255) as i32 - expected_green).abs() <= 1);
                }
                images.push(pixels);
            }
            assert_eq!(images[0], images[1], "expanded/native batch framebuffer, variant={variant}");
        }
    }
    eprintln!("kirikae: instance stream parity passed 27 cases (native batching {native_enabled}, native input {instance_streams}, pending input {pending_streams})");
}
