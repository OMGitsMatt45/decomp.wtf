//! Original MIT qualification scene. Real Maxwell pushbuffers and shaders are
//! consumed by the same Vulkan path as a game; this is a host GPU test, not a
//! claim that its draw commands came from translated guest CPU instructions.
use kirikae_rt::{gpu::{Gpu, CLASS_2D, CLASS_3D}, mem::GuestMemory};
use serde_json::json;
use std::{path::PathBuf, sync::atomic::Ordering};
const PT: u64 = 7 << 16;
const EXIT: u64 = 0xe300_0000_0000_0000 | PT | 0xf;
const NOP: u64 = 0x50b0_0000_0000_0000 | PT | 0xf00;
fn shader(fragment: bool, insns: &[u64]) -> Vec<u8> {
    let mut header = [0u32; 20];
    header[0] = if fragment { 2 | 5 << 10 } else { 1 | 1 << 10 };
    if fragment { header[18] = 0xf; header[6] = 0b1010; }
    let mut out: Vec<u8> = header.iter().flat_map(|v| v.to_le_bytes()).collect();
    for block in insns.chunks(3) {
        out.extend_from_slice(&0u64.to_le_bytes());
        for i in 0..3 { out.extend_from_slice(&block.get(i).copied().unwrap_or(NOP).to_le_bytes()); }
    }
    out.resize(0x1000, 0); out
}
fn mov(rd: u64, x: f32) -> u64 { 0x0100_0000_0000_0000 | (x.to_bits() as u64) << 20 | PT | rd }
fn method(out: &mut Vec<u32>, m: u32, values: &[u32]) {
    out.push(1 << 29 | (values.len() as u32) << 16 | m); out.extend_from_slice(values);
}
fn address(out: &mut Vec<u32>, m: u32, addr: u64) { method(out, m, &[(addr >> 32) as u32, addr as u32]); }

fn pitch_blit(gpu: &Gpu, mem: &GuestMemory) {
    let (width, height, pitch) = (16, 8, 64);
    // The GPU mapping adds 0x100000 to these low address words to find CPU RAM.
    let (source, destination, alternate) = (0x40000, 0x50000, 0x60000);
    let cpu_address = |address| 0x100000 + u64::from(address);
    let blit = |source, destination, destination_pitch, corner_origin| {
        let mut cp = Vec::new();
        method(&mut cp, 0, &[CLASS_2D]);
        // R8_UNORM destination and source, then a full-surface point copy.
        method(&mut cp, 0x80, &[
            0xf3, u32::from(destination_pitch != 0), 0, 0, 0, destination_pitch, width, height, 1, destination,
        ]);
        method(&mut cp, 0x8c, &[0xf3, 1, 0, 0, 0, pitch, width, height, 1, source]);
        method(&mut cp, 0x223, &[u32::from(corner_origin)]);
        let phase = if corner_origin { 0x8000_0000 } else { 0 };
        method(&mut cp, 0x22c, &[0, 0, width, height, 0, 1, 0, 1, phase, 0, phase, 0]);
        let bytes: Vec<u8> = cp.iter().flat_map(|v| v.to_le_bytes()).collect();
        assert!(mem.write(0x300000, &bytes));
        gpu.submit(mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
    };
    let write = |address, value| {
        let mut rows = vec![0xff; (pitch * height) as usize];
        for row in rows.chunks_exact_mut(pitch as usize) {
            row[..width as usize].fill(value);
        }
        assert!(mem.write(cpu_address(address), &rows));
    };
    let check = |value| {
        let pixels = gpu.read_pixels(cpu_address(destination), width, height).expect("Vulkan 2D blit readback");
        assert!(pixels.iter().all(|&p| p == u32::from(value) * 0x010101),
            "Pitch source value {value:#x}, first destination pixel {:#x}", pixels[0]);
    };
    for value in [0x32, 0xa4] {
        write(source, value);
        blit(source, destination, 0, false);
        check(value);
    }

    // A GPU-produced version of the same pitched image takes priority over
    // the old CPU bytes when used as the source of another blit.
    write(alternate, 0x57);
    blit(alternate, source, pitch, false);
    assert_eq!(mem.read(cpu_address(source), 1).unwrap(), [0xa4]);
    blit(source, destination, 0, false);
    check(0x57);

    // A coordinate ramp exposes the shift and rescale caused by rounding
    // half-texel positions before submitting the Vulkan point copy.
    let mut rows = vec![0xff; (pitch * height) as usize];
    let expected: Vec<_> = (0..height).flat_map(|y| (0..width).map(move |x| y * width + x)).collect();
    for (index, &value) in expected.iter().enumerate() {
        let index = index as u32;
        rows[(index / width * pitch + index % width) as usize] = value as u8;
    }
    assert!(mem.write(cpu_address(alternate), &rows));
    blit(alternate, destination, 0, true);
    let pixels = gpu.read_pixels(cpu_address(destination), width, height).expect("Vulkan corner-origin point copy");
    assert_eq!(pixels, expected.iter().map(|v| v * 0x010101).collect::<Vec<_>>());
}

fn texture_remap(gpu: &Gpu, mem: &GuestMemory) {
    let (texture, alias) = (0x2_0000_0000, 0x2_0001_0000);
    let (first, second) = (0x170000, 0x171000);
    assert!(mem.write(first, &[255, 0, 0, 255]));
    assert!(mem.write(second, &[0, 255, 0, 255]));
    gpu.map(texture, first, 0x1000);
    gpu.map(alias, first, 0x1000);

    let words = |data: &[u32]| data.iter().flat_map(|word| word.to_le_bytes()).collect::<Vec<_>>();
    let rgba8 = 0x08 | 2 << 7 | 2 << 10 | 2 << 13 | 2 << 16
        | 2 << 19 | 3 << 22 | 4 << 25 | 5 << 28;
    let tic = |address: u64| [rgba8, address as u32, (address >> 32) as u32 | 1 << 21, 1, 1 << 23, 0, 0, 0];
    assert!(mem.write(0x180000, &words(&tic(texture))));
    assert!(mem.write(0x180020, &words(&tic(alias))));
    assert!(mem.write(0x180040, &[0; 32]));
    // TEXS samples a 1x1 RGBA8 texture at its center. Handle zero reads cbuf slot 0.
    let sample = 0xd800_0000_0000_0000 | 1 << 53 | 4 << 50 | 2 << 28 | 5 << 20 | PT | 4 << 8;
    assert!(mem.write(0x121000, &shader(true, &[mov(4, 0.5), mov(5, 0.5), sample, EXIT])));

    // Reuse the probe triangle and render target from the previous test.
    let draw = |index| {
        assert!(mem.write(0x180060, &words(&[index])));
        let mut cp = Vec::new();
        method(&mut cp, 0, &[CLASS_3D]);
        method(&mut cp, 0x646, &[0]);
        method(&mut cp, 0x850, &[1, 0x21000]);
        address(&mut cp, 0x55d, 0x1_0008_0000);
        address(&mut cp, 0x557, 0x1_0008_0040);
        method(&mut cp, 0x8e0, &[32]);
        address(&mut cp, 0x8e1, 0x1_0008_0060);
        method(&mut cp, 0x924, &[1]);
        method(&mut cp, 0x674, &[0x3c]);
        method(&mut cp, 0x586, &[4]);
        method(&mut cp, 0x35e, &[3]);
        method(&mut cp, 0x585, &[0]);
        assert!(mem.write(0x300000, &words(&cp)));
        gpu.submit(mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
        let pixels = gpu.read_pixels(0x200000, 128, 96).expect("texture remap readback");
        pixels[48 * 128 + 64] & 0xffffff
    };

    let before = draw(0);
    gpu.map(texture, second, 0x1000);
    assert_eq!(gpu.translate(texture), Some(second));
    let after = draw(0);
    let unchanged_alias = draw(1);
    assert_eq!([before, after, unchanged_alias], [0xff0000, 0x00ff00, 0xff0000],
        "texture remap RGB before={before:06x}, after={after:06x}, alias={unchanged_alias:06x}");
}

fn main() {
    let root = PathBuf::from(std::env::args().nth(1).expect("output directory"));
    std::fs::create_dir_all(&root).unwrap();
    let renderer = std::env::args().nth(2).unwrap_or_else(|| "software".into());
    assert!(matches!(renderer.as_str(), "software" | "auto"));
    unsafe { std::env::set_var("KIRIKAE_HEADLESS", "1"); std::env::set_var("DECOMP_SWITCH_RENDERER", &renderer); }
    let mem = GuestMemory::new().unwrap(); mem.map(0x100000, 0x300000).unwrap();
    let gpu = Gpu::default(); gpu.map(0x1_0000_0000, 0x100000, 0x300000);
    let ald = 0xefd8_0000_0000_0000 | 3 << 47 | 0xff << 39 | 0x80 << 20 | PT | 0xff << 8;
    let ast = 0xeff0_0000_0000_0000 | 3 << 47 | 0xff << 39 | 0x70 << 20 | PT | 0xff << 8;
    assert!(mem.write(0x110000, &shader(false, &[ald, ast, EXIT])));
    assert!(mem.write(0x120000, &shader(true, &[mov(0, 1.0), mov(1, 0.0), mov(2, 0.0), mov(3, 1.0), EXIT])));
    let vertices: [f32; 12] = [-0.75,-0.75,0.5,1.0, 0.75,-0.75,0.5,1.0, 0.0,0.75,0.5,1.0];
    assert!(mem.write(0x130000, &vertices.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
    let mut frames = Vec::new();
    // Counter-clockwise in guest clip coordinates; clockwise on a Vulkan
    // positive-height viewport. Test the origin mode, the separate FLIP_Y bit,
    // both guest front-face settings and both signs of viewport height.
    let mut cases = vec![(128,96,false,0,false,false,true), (256,192,false,0,false,false,true)];
    for origin in [0, 1, 0x10, 0x11] {
        for clockwise in [false, true] {
            for negative_height in [false, true] {
                let flip_y = origin & 0x10 != 0;
                let visible = (clockwise == (origin & 1 != 0)) ^ flip_y ^ negative_height;
                cases.push((128,96,true,origin,clockwise,negative_height,visible));
            }
        }
    }
    for (width, height, cull, origin, clockwise, negative_height, visible) in cases {
        let mut cp = Vec::new();
        method(&mut cp, 0, &[CLASS_3D]);
        address(&mut cp, 0x200, 0x1_0010_0000);
        method(&mut cp, 0x202, &[width * 4, height, 0xd5, 1 << 12]);
        method(&mut cp, 0x487, &[1]);
        method(&mut cp, 0x680, &[0x1111]);
        method(&mut cp, 0x4eb, &[origin]);
        method(&mut cp, 0x646, &[u32::from(cull), if clockwise { 0x900 } else { 0x901 }, 0x405]);
        let sx = width as f32 / 2.0; let sy = height as f32 / 2.0;
        method(&mut cp, 0x280, &[sx.to_bits(), (if negative_height { -sy } else { sy }).to_bits(),
            0.5f32.to_bits(), sx.to_bits(), sy.to_bits(), 0.5f32.to_bits()]);
        method(&mut cp, 0x363, &[1f32.to_bits()]);
        method(&mut cp, 0x674, &[0x3c]);
        address(&mut cp, 0x582, 0x1_0000_0000);
        method(&mut cp, 0x810, &[1, 0x10000]);
        method(&mut cp, 0x850, &[1, 0x20000]);
        method(&mut cp, 0x458, &[1 << 21 | 7 << 27]);
        method(&mut cp, 0x700, &[16]); address(&mut cp, 0x701, 0x1_0003_0000);
        address(&mut cp, 0x7c0, 0x1_0003_002f);
        method(&mut cp, 0x586, &[4]); method(&mut cp, 0x35e, &[3]); method(&mut cp, 0x585, &[0]);
        assert!(mem.write(0x300000, &cp.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
        gpu.submit(&mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
        let pixels = gpu.read_pixels(0x200000, width, height).expect("Vulkan image readback");
        let red = pixels.iter().filter(|&&p| p & 0xffffff == 0xff0000).count();
        assert_eq!(pixels[(height/2 * width + width/2) as usize] & 0xffffff,
            if visible { 0xff0000 } else { 0 }, "triangle center: cull={cull} origin={origin} clockwise={clockwise} negative_height={negative_height}");
        assert_eq!(pixels[0] & 0xffffff, 0, "clear outside geometry");
        let expected = if visible { (width * height) as f64 * 9.0/32.0 } else { 0.0 };
        assert!((red as f64 - expected).abs() < (width + height) as f64, "triangle area {red}, expected {expected}");
        let rgb: Vec<u8> = pixels.iter().flat_map(|p| [(p>>16) as u8,(p>>8) as u8,*p as u8]).collect();
        std::fs::write(root.join(format!("triangle-{width}x{height}-cull{cull}-origin{origin}-cw{clockwise}-negative{negative_height}.png")), kirikae_rt::usage::png(width, height, &rgb)).unwrap();
        frames.push(json!({"width":width,"height":height,"red_pixels":red,"expected_area":expected,
            "cull":cull,"window_origin":origin,"clockwise":clockwise,"negative_viewport_height":negative_height,"visible":visible}));
    }
    pitch_blit(&gpu, &mem);
    let stats = gpu.render_stats().expect("Vulkan renderer");
    assert_eq!(stats.draws, 18); assert_eq!(stats.skipped, 0); assert!(stats.skip_reasons.is_empty());
    let report = json!({"schema":"decomp.wtf.switch-graphics-probe/v1", "status":"passed", "cpu_path":"host qualification scene",
        "renderer":kirikae_rt::decomp::RENDERER.lock().unwrap().clone(), "frames":frames,
        "pushbuffer_submits":gpu.stats.submits.load(Ordering::Relaxed), "draws":stats.draws,"skipped":stats.skipped});
    texture_remap(&gpu, &mem);
    gpu.shutdown();
    std::fs::write(root.join("graphics-report.json"), serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("{report}");
}
