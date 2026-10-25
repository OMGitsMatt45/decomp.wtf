//! Independent host for the generated C and source-shipped 3DS runtime.
use std::ffi::c_void;
use std::io::Read;
use std::path::PathBuf;
use std::ptr::addr_of;
use sha2::{Digest, Sha256};
use zakuro_core::{loader, Config, StepOutcome};

include!("identity.rs");
#[cfg(feature="desktop")]
mod desktop;

fn advance(system:&mut zakuro_core::System,deadline:u64)->Option<&'static str> {
    let outcome=system.step(Some(deadline));
    // Even a service that exits must not hide unsupported operations in the
    // same step. These errors remain visible with compatibility enabled.
    if !system.unimplemented_svcs.is_empty() || !system.services.unimplemented.is_empty() {
        return Some("unimplemented-service");
    }
    match outcome {
        StepOutcome::Ran=>None, StepOutcome::Exited=>Some("exit-process"), StepOutcome::Faulted=>Some("fault")
    }
}

extern "C" {
    static recomp_abi: u32;
    static recomp_generation: u32;
    static recomp_entry_count: u32;
    static recomp_entries: u8;
    static recomp_module_count: u32;
    static recomp_modules: u8;
    static recomp_origins: u8;
}

fn identity(path: &PathBuf) -> Result<String, Box<dyn std::error::Error>> {
    let mut file = std::fs::File::open(path)?;
    if file.metadata()?.len() != INPUT_SIZE { return Err("original input size differs".into()); }
    let mut hash = Sha256::new();
    let mut bytes = [0u8; 65536];
    loop {
        let count = file.read(&mut bytes)?;
        if count == 0 { break; }
        hash.update(&bytes[..count]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn run() -> Result<i32, Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let Some(input) = args.next() else {
        return Err("usage: ctr_runtime ORIGINAL_IMAGE [--window] [--screens stacked|unified] [--primary top|bottom] [--cycles N] [--data DIRECTORY] [--allow-interpreter] [--gpu]".into());
    };
    let input = PathBuf::from(input);
    let mut cycles: u64 = 1_000_000;
    let mut data = PathBuf::from("user");
    let mut fallback = false;
    let mut gpu = false;
    let mut scale = 1;
    let mut window = false;
    let mut unified = DEFAULT_UNIFIED;
    let mut bottom_primary = false;
    let mut frame_limit:Option<u64> = None;
    let mut explicit_cycles = false;
    let mut layout_option = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--cycles" => {cycles = args.next().ok_or("--cycles needs a value")?.parse()?;explicit_cycles=true;}
            "--data" => data = args.next().ok_or("--data needs a directory")?.into(),
            "--allow-interpreter" => fallback = true,
            "--gpu" => gpu = true,
            "--scale" => scale = args.next().ok_or("--scale needs a value")?.parse()?,
            "--window" => window = true,
            "--screens" => {layout_option=true; unified = match args.next().as_deref() {
                Some("stacked")=>false,Some("unified")=>true,_=>return Err("--screens expects stacked or unified".into())};}
            "--primary" => {layout_option=true; bottom_primary = match args.next().as_deref() {
                Some("top")=>false,Some("bottom")=>true,_=>return Err("--primary expects top or bottom".into())};}
            "--window-frames" => frame_limit=Some(args.next().ok_or("--window-frames needs a value")?.parse()?),
            _ => return Err(format!("unknown option: {arg}").into()),
        }
    }
    if !(1..=1_000_000_000).contains(&cycles) { return Err("cycle budget must be 1 through 1000000000".into()); }
    if scale==0 {return Err("render scale must be positive".into());}
    if frame_limit==Some(0) {return Err("window frame limit must be positive".into());}
    if !window && (layout_option || frame_limit.is_some()) {
        return Err("screen options require --window".into());
    }
    if window && !cfg!(feature="desktop") {return Err("rebuild with CTR_DESKTOP=ON for --window".into());}
    if identity(&input)? != INPUT_SHA256 { return Err("original input SHA-256 differs; use the exported revision".into()); }
    // SAFETY: CMake links these exact C tables and their ABI. Code provenance
    // guards stay enabled for relocated or modified executable memory.
    let code = unsafe {
        zakuro_core::recompiled::Linked::new(TITLE_ID, recomp_abi,
            addr_of!(recomp_entries) as *const c_void, recomp_entry_count,
            addr_of!(recomp_modules) as *const c_void, recomp_module_count)
            .with_origins(recomp_generation, addr_of!(recomp_origins) as *const c_void)
    };
    let device = if gpu && !window {
        Some(std::sync::Arc::new(zakuro_gpu::SharedDevice::new()
            .map_err(|error|format!("Vulkan geometry device: {error}"))?))
    } else { None };
    let mut system = loader::load(&input, Config {
        linked: Some(code), find_recompiled: false, strict_static: !fallback,
        data_dir: Some(data), hardware_renderer: gpu && !window, resolution: scale,
        texture_packs: false, clock: Some(0), device, ..Config::default()
    })?;
    let library = system.recompiled.as_mut().ok_or("linked translated C was not accepted")?;
    library.forbid_fallback = !fallback;
    if gpu && !window && !system.gpu.draws_on_gpu() {
        return Err("requested Vulkan geometry renderer could not initialize; no software fallback was selected".into());
    }
    let mut stopped = "budget";
    #[allow(unused_mut)]
    let mut window_report=serde_json::Value::Null;
    if window {
        #[cfg(feature="desktop")]
        {
            let outcome=desktop::run(&mut system,explicit_cycles.then_some(cycles),frame_limit,unified,bottom_primary)?;
            stopped=outcome.stop;
            window_report=serde_json::json!({"presented_frames":outcome.presented,"drawable":outcome.drawable,
                "screens":if outcome.unified {"unified"} else {"stacked"},
                "primary":if outcome.bottom_primary {"bottom"} else {"top"},"physical_device_qualified":false,
                "audio_playback":false,"continuous_scene_qualified":false});
        }
    } else {
        while system.cpu.cycles < cycles {
            if let Some(stop)=advance(&mut system,cycles) {stopped=stop;break;}
        }
    }
    if let Some(at) = system.recompiled.as_ref().and_then(|code| code.rejected.get()) {
        system.static_misses.insert(at);
    }
    let inline = system.recompiled.as_ref().map_or(0, |code| code.fallbacks());
    let rejected = system.recompiled.as_ref().map_or(0, |code| code.rejected_count.get());
    let report = serde_json::json!({
        "schema":"decomp.wtf.3ds-runtime-run/v1", "stop":stopped,
        "process_exited":system.exited, "r0":system.cpu.regs[0], "r1":system.cpu.regs[1],
        "cycles":system.cpu.cycles, "frames":system.frames,
        "native_instructions":system.recompiled_instructions.saturating_sub(inline + rejected),
        "interpreted_instructions":system.interpreted_instructions + inline,
        "rejected_instructions":rejected,
        "interpreter_allowed":fallback, "static_misses":system.static_misses,
        "unimplemented_svcs":system.unimplemented_svcs,
        "unimplemented_services":system.services.unimplemented.iter().collect::<Vec<_>>(),
        "services":system.services_seen,
        "gpu_rendering":system.gpu.draws_on_gpu(), "render_scale":system.gpu.scale(),
        "graphics_qualified":false, "retail_qualified":false,
        "input_sha256":INPUT_SHA256
        ,"window":window_report
    });
    println!("{report}");
    Ok(if matches!(stopped,"exit-process"|"window-closed"|"window-frame-limit") {0} else if stopped == "budget" {2} else {1})
}

fn main() {
    match run() {
        Ok(status) => std::process::exit(status),
        Err(error) => { eprintln!("3DS runtime: {error}"); std::process::exit(1); }
    }
}
