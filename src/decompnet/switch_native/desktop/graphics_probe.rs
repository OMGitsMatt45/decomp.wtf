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

fn texture_updates(gpu: &Gpu, mem: &GuestMemory) {
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

    // An 8x8 BC1 texture has two mip levels in two 512-byte GOBs.
    // Fill the four level-zero blocks with one endpoint and leave mip 1 red.
    let (mip_texture, backing) = (0x2_0002_0000u64, 0x172000);
    let block = |endpoint: u16| {
        let mut bytes = [0; 8];
        bytes[..2].copy_from_slice(&endpoint.to_le_bytes());
        bytes
    };
    let mut texels = [0; 1024];
    for chunk in texels[..32].chunks_exact_mut(8) {
        chunk.copy_from_slice(&block(0xf800));
    }
    texels[512..520].copy_from_slice(&block(0xf800));
    assert!(mem.write(backing, &texels));
    gpu.map(mip_texture, backing, 0x1000);
    let bc1 = rgba8 & !0x7f | 0x24;
    let mut tic = [bc1, mip_texture as u32, (mip_texture >> 32) as u32 | 3 << 21,
        1 << 28, 7 | 1 << 23, 7, 0, 1 << 4];
    assert!(mem.write(0x180000, &words(&tic)));
    let before = draw(0);
    for chunk in texels[..32].chunks_exact_mut(8) {
        chunk.copy_from_slice(&block(0x07e0));
    }
    assert!(mem.write(backing, &texels));
    kirikae_rt::display::FRAMES.fetch_add(30, Ordering::Relaxed);
    let after = draw(0);
    assert_eq!([before, after], [0xff0000, 0x00ff00],
        "mipmapped BC1 refresh RGB before={before:06x}, after={after:06x}");

    // A descriptor for the second layer must still sample that layer of the
    // previously uploaded array, while the descriptor at its base samples layer 0.
    let (array_texture, array_backing) = (0x2_0003_0000u64, 0x174000);
    let mut array = texels.repeat(2);
    for chunk in array[1024..1056].chunks_exact_mut(8) {
        chunk.copy_from_slice(&block(0x001f));
    }
    assert!(mem.write(array_backing, &array));
    gpu.map(array_texture, array_backing, 0x1000);
    tic[1] = array_texture as u32;
    tic[5] |= 1 << 16;
    assert!(mem.write(0x180000, &words(&tic)));
    let layer_zero = draw(0);
    tic[1] += 1024;
    tic[5] &= !(1 << 16);
    assert!(mem.write(0x180000, &words(&tic)));
    let layer_one = draw(0);
    assert_eq!([layer_zero, layer_one], [0x00ff00, 0x0000ff],
        "mipmapped array RGB layer 0={layer_zero:06x}, layer 1={layer_one:06x}");
}

fn primitive_restart(gpu: &Gpu, mem: &GuestMemory) {
    let vertices = [
        [-0.95f32, -0.75, 0.5, 1.0], [-0.45, -0.75, 0.5, 1.0], [-0.70, 0.65, 0.5, 1.0],
        [0.0, 0.8, 0.5, 1.0],
        [0.45, -0.75, 0.5, 1.0], [0.95, -0.75, 0.5, 1.0], [0.70, 0.65, 0.5, 1.0],
    ];
    let vertex_bytes: Vec<_> = vertices.iter().flatten().flat_map(|v| v.to_le_bytes()).collect();
    assert!(mem.write(0x130000, &vertex_bytes));
    let draw = |format, restart: Option<u32>| {
        let mut cp = Vec::new();
        method(&mut cp, 0, &[CLASS_3D]);
        method(&mut cp, 0x4eb, &[0]);
        method(&mut cp, 0x646, &[0]);
        method(&mut cp, 0x850, &[1, 0x20000]);
        let sx = 64f32.to_bits(); let sy = 48f32.to_bits();
        method(&mut cp, 0x280, &[sx, sy, 0.5f32.to_bits(), sx, sy, 0.5f32.to_bits()]);
        address(&mut cp, 0x7c0, 0x1_0003_006f);
        address(&mut cp, 0x5f2, 0x1_0009_0000);
        method(&mut cp, 0x5f6, &[format, 0]);
        method(&mut cp, 0x591, &[u32::from(restart.is_some()), restart.unwrap_or(0)]);
        method(&mut cp, 0x674, &[0x3c]);
        method(&mut cp, 0x586, &[5]);
        method(&mut cp, 0x5f8, &[7]);
        method(&mut cp, 0x585, &[0]);
        assert!(mem.write(0x300000, &cp.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
        gpu.submit(mem, &[0x1_0020_0000 | (cp.len() as u64) << 42]).unwrap();
        let pixels = gpu.read_pixels(0x200000, 128, 96).expect("primitive restart readback");
        [19, 64, 109].map(|x| pixels[48 * 128 + x] & 0xffffff)
    };

    for format in 0..3u32 {
        let indices: Vec<_> = (0..7u32).flat_map(|i| i.to_le_bytes().into_iter().take(1 << format)).collect();
        assert!(mem.write(0x190000, &indices));
        // Repeated draws promote each converted buffer. Change the restart
        // register while keeping the bytes and the pipeline topology identical.
        for restart in [None, Some(3), Some(7), Some(3), None] {
            for _ in 0..3 {
                let expected_center = if restart == Some(3) { 0 } else { 0xff0000 };
                assert_eq!(draw(format, restart), [0xff0000, expected_center, 0xff0000],
                    "indexed strip: format {format}, restart {restart:?}");
            }
        }
    }
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
    texture_updates(&gpu, &mem);
    primitive_restart(&gpu, &mem);
    gpfifo_continuation(&gpu, &mem);
    gpu.shutdown();
    std::fs::write(root.join("graphics-report.json"), serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("{report}");
}

fn gpfifo_continuation(gpu: &Gpu, mem: &GuestMemory) {
    const CODE: [u32; 31] = [
        0x00000601, 0x00000501, 0x0346c215, 0x017dc061, 0x01118451,
        0x00002041, 0x05434021, 0x00002331, 0x00001841, 0x0638c021,
        0x01900041, 0x00155510, 0x00002041, 0x0002e807, 0x00001841,
        0x01618021, 0x00000841, 0x017e0021, 0x00003041, 0x01614071,
        0xffffed11, 0x00004211, 0xfffe6817, 0xd0808912, 0x01118071,
        0x01434071, 0x01438071, 0x0638c021, 0x01900041, 0x000000c1, 0x00000041,
    ];
    let ald = |rd: u64, at: u64, count: u64| 0xefd8_0000_0000_0000u64 | (count - 1) << 47 | 0xff << 39 | at << 20 | PT | 0xff << 8 | rd;
    let ast = |rd: u64, at: u64| 0xeff0_0000_0000_0000u64 | 3 << 47 | 0xff << 39 | at << 20 | PT | 0xff << 8 | rd;
    let imm = |op: u64, rd: u64, ra: u64, value: f32| op | (value.to_bits() as u64) << 20 | PT | ra << 8 | rd;
    let vs = [ald(0, 0x80, 4), ald(4, 0x2f8, 1),
        0x5cb8_0000_0000_0000 | 2 << 10 | 2 << 8 | PT | 4 << 20 | 4,
        imm(0x1e00_0000_0000_0000, 5, 4, 0.25),
        imm(0x0800_0000_0000_0000, 5, 5, -0.75),
        0x5c58_0000_0000_0000 | 5 << 20 | PT,
        ast(0, 0x70), imm(0x0800_0000_0000_0000, 4, 4, 1.0),
        imm(0x1e00_0000_0000_0000, 4, 4, 0.125),
        mov(5, 0.0), mov(6, 0.0), mov(7, 1.0), ast(4, 0x80), EXIT];
    assert!(mem.write(0x1a2000, &shader(false, &vs)));
    assert!(mem.write(0x1b1000, &shader(true, &[ald(0, 0x80, 4), EXIT])));
    let vertices = [0f32, 0., 0., 0., 0., 0., 0., 0.,
        -0.08, -0.30, 0.5, 1.0, 0.08, -0.30, 0.5, 1.0, 0.0, 0.30, 0.5, 1.0];
    assert!(mem.write(0x130000, &vertices.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
    let indices: Vec<u16> = (0..306).map(|index| if index < 36 { 99 } else { 2 + ((index - 36) % 3) }).collect();
    assert!(mem.write(0x190000, &indices.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
    let mut setup = Vec::new();
    method(&mut setup, 0, &[CLASS_3D]);
    method(&mut setup, 0x4eb, &[0]); method(&mut setup, 0x646, &[0]);
    method(&mut setup, 0x280, &[64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits(), 64f32.to_bits(), 48f32.to_bits(), 0.5f32.to_bits()]);
    method(&mut setup, 0x810, &[1, 0xa2000]); method(&mut setup, 0x850, &[1, 0xb1000]);
    method(&mut setup, 0x458, &[1 << 21 | 7 << 27]); method(&mut setup, 0x700, &[16]);
    address(&mut setup, 0x701, 0x1_0003_0000); address(&mut setup, 0x7c0, 0x1_0003_004f);
    address(&mut setup, 0x5f2, 0x1_0009_0000); method(&mut setup, 0x5f6, &[1, 36]); method(&mut setup, 0x591, &[0, 0]);
    method(&mut setup, 0x45, &[0]); for word in CODE { method(&mut setup, 0x46, &[word]); }
    method(&mut setup, 0x47, &[29]); method(&mut setup, 0x48, &[0]); method(&mut setup, 0xd1b, &[u32::MAX]);
    assert!(mem.write(0x300000, &setup.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
    gpu.submit(mem, &[0x1_0020_0000 | (setup.len() as u64) << 42]).unwrap();

    // Exact captured kind-5 packet and indexed-indirect parameters; deliberately
    // include zero arguments that the old entry-local parser treated as headers.
    let words = [0xa006_0e3au32, 4, 270, 7, 36, 0, 258447, 0x9100_0002];
    assert!(mem.write(0x310000, &words.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
    let entry = |offset: usize, length: usize| 0x1_0021_0000 | (offset as u64 * 4) | (length as u64) << 42;
    let mut reference = None;
    let mut cases = 0;
    for separate_submits in [false, true] {
        for split in 0..=words.len() {
            let mut clear = Vec::new(); method(&mut clear, 0x674, &[0x3c]);
            assert!(mem.write(0x300000, &clear.iter().flat_map(|v| v.to_le_bytes()).collect::<Vec<_>>()));
            gpu.submit(mem, &[0x1_0020_0000 | (clear.len() as u64) << 42]).unwrap();
            let before = gpu.render_stats().unwrap();
            let before_macros = gpu.stats.macros.load(Ordering::Relaxed);
            let entries = [entry(0, split), entry(split, 0), entry(split, words.len() - split)];
            if separate_submits {
                for part in entries { gpu.submit(mem, &[part]).unwrap(); }
            } else { gpu.submit(mem, &entries).unwrap(); }
            let pixels = gpu.read_pixels(0x200000, 128, 96).expect("split GPFIFO readback");
            let after = gpu.render_stats().unwrap();
            assert_eq!(gpu.stats.macros.load(Ordering::Relaxed) - before_macros, 1);
            assert_eq!(after.draws - before.draws, 7, "split {split}, separate submits {separate_submits}");
            assert_eq!(after.skipped, before.skipped);
            for (slot, x) in [16usize, 32, 48, 64, 80, 96, 112].into_iter().enumerate() {
                let pixel = pixels[48 * 128 + x];
                let expected = ((slot + 1) * 255) as i32 / 8;
                assert!(((pixel >> 16 & 255) as i32 - expected).abs() <= 1,
                    "instance {slot}: {pixel:06x}, split {split}, separate {separate_submits}");
            }
            if let Some(expected) = &reference { assert_eq!(&pixels, expected, "split {split}, separate submits {separate_submits}"); }
            else { reference = Some(pixels); }
            cases += 1;
        }
    }
    eprintln!("kirikae: split GPFIFO qualification passed {cases} cases, seven distinct InstanceIndex positions/colors, exact 270/7/36/0/258447 arguments");
}
