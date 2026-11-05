//! Native C guest ABI on the complete source-shipped Kirikae host runtime.
use std::{ffi::{CStr, CString, c_char, c_void}, path::PathBuf, sync::{OnceLock, atomic::Ordering}};
use serde_json::{Value, json};
use crate::{Cpu, Entry, HALT_PC};

#[repr(C, align(16))]
pub struct NativeCpu {
    x: [u64; 32], sp: u64, pc: u64, nzcv: u64, tpidr: u64, tpidrro: u64,
    excl_addr: u64, excl_lo: u64, owner: *mut c_void, fpcr: u64, fpsr: u64,
    excl_hi: u64, pad: [u8; 168], v: [u128; 32],
}
const _: () = assert!(std::mem::size_of::<NativeCpu>() == 1024);
const _: () = assert!(std::mem::offset_of!(NativeCpu, v) == 512);

#[repr(C)]
struct ModuleInfo {
    name: *const c_char, file: *const c_char, sha256: *const c_char,
    base: u64, size: u64, text_offset: u64, text_size: u64, ro_offset: u64, ro_size: u64,
    data_offset: u64, data_size: u64, bss_size: u64,
    addresses: *const u64, functions: *const c_void, count: *const u64,
}

unsafe extern "C" {
    fn sw_module_count() -> usize;
    fn sw_module_at(index: usize) -> *const ModuleInfo;
    fn sw_initializers(count: *mut usize) -> *const u64;
    fn sw_sdk_initializers(count: *mut usize) -> *const u64;
    fn sw_main_initializers(count: *mut usize) -> *const u64;
    fn sw_sdk_startup() -> u64;
    fn sw_entry() -> u64;
    fn sw_stack_size() -> u64;
    fn sw_title_id() -> u64;
    fn sw_input_sha256() -> *const c_char;
    fn sw_backend_revision() -> *const c_char;
    fn sw_romfs_sha256() -> *const c_char;
    fn sw_initialize();
    fn sw_enter(c: *mut NativeCpu, memory_base: usize, unhooked: u64);
    fn switch_asset_matches_expected(path: *const c_char, expected: *const c_char) -> i32;
}

struct Code {
    base: u64, text: Vec<u8>, entries: Vec<u64>,
}
struct Config {
    code: Vec<Code>, initializers: Vec<u64>, entry: u64, samples: Vec<(String, u64, u64)>,
    sdk_startup: u64, sdk_initializers: Vec<u64>, main_initializers: Vec<u64>,
}
static CONFIG: OnceLock<Config> = OnceLock::new();
static REPORT: OnceLock<PathBuf> = OnceLock::new();
const STARTUP: u64 = 0x7f_fe00_0000;

fn copy_from_native(n: &NativeCpu, c: &mut Cpu) {
    c.x.copy_from_slice(&n.x[..31]); c.sp = n.sp; c.pc = n.pc; c.nzcv = n.nzcv;
    c.tpidr_el0 = n.tpidr; c.tpidrro_el0 = n.tpidrro; c.fpcr = n.fpcr; c.fpsr = n.fpsr;
    c.excl_addr = n.excl_addr; c.excl_lo = n.excl_lo; c.excl_hi = n.excl_hi;
    for i in 0..32 { c.v[i] = [n.v[i] as u64, (n.v[i] >> 64) as u64]; }
}
fn copy_to_native(c: &Cpu, n: &mut NativeCpu) {
    n.x[..31].copy_from_slice(&c.x); n.sp = c.sp; n.pc = c.pc; n.nzcv = c.nzcv;
    n.tpidr = c.tpidr_el0; n.tpidrro = c.tpidrro_el0; n.fpcr = c.fpcr; n.fpsr = c.fpsr;
    n.excl_addr = c.excl_addr; n.excl_lo = c.excl_lo; n.excl_hi = c.excl_hi;
    for i in 0..32 { n.v[i] = c.v[i][0] as u128 | (c.v[i][1] as u128) << 64; }
}
fn callback(n: &mut NativeCpu, f: impl FnOnce(&mut Cpu)) -> i32 {
    // The C scope owns n; owner is the distinct live guest-thread Cpu. All
    // Rust frames return before the C scope performs its nonlocal exit.
    let c = unsafe { &mut *n.owner.cast::<Cpu>() };
    copy_from_native(n, c);
    f(c);
    if c.process().sched.exiting.load(Ordering::Relaxed) { c.halt(); }
    copy_to_native(c, n);
    c.halted as i32
}
fn enter(c: &mut Cpu, skip_hook: bool) {
    let mut n = NativeCpu { x: [0; 32], sp: 0, pc: 0, nzcv: 0, tpidr: 0, tpidrro: 0,
        excl_addr: 0, excl_lo: 0, owner: (c as *mut Cpu).cast(), fpcr: 0, fpsr: 0, excl_hi: 0, pad: [0; 168], v: [0; 32] };
    copy_to_native(c, &mut n);
    unsafe { sw_enter(&mut n, c.process().memory.base() as usize, if skip_hook { c.pc } else { u64::MAX }); }
    copy_from_native(&n, c);
}
pub extern "C" fn entry(c: &mut Cpu) { enter(c, false); }
pub extern "C" fn unhooked(c: &mut Cpu) { enter(c, true); }

// This guard runs under the guest FP environment. Keep it integer-only: no
// formatting, service calls, register synchronization or floating-point work.
// A rejected guard takes the existing full callback for hooks and diagnostics.
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_entry_is_plain(n: &NativeCpu, address: u64, skip: i32) -> i32 {
    let c = unsafe { &*n.owner.cast::<Cpu>() };
    let p = c.process();
    if p.sched.exiting.load(Ordering::Relaxed) || (skip == 0 && p.hle.owns(address)) { return 0; }
    let Some(config) = CONFIG.get() else { return 0; };
    let Some(code) = config.code.iter().find(|m| address >= m.base && address < m.base + m.text.len() as u64) else { return 0; };
    let Ok(index) = code.entries.binary_search(&address) else { return 0; };
    let offset = (address - code.base) as usize;
    let end = code.entries.get(index + 1).copied().unwrap_or(code.base + code.text.len() as u64);
    let size = (end - address) as usize;
    let bytes = unsafe { std::slice::from_raw_parts(p.memory.base().add(address as usize), size) };
    if bytes != &code.text[offset..offset + size] { return 0; }
    crate::decomp::NATIVE.fetch_add(1, Ordering::Relaxed);
    1
}

#[unsafe(no_mangle)]
pub extern "C" fn sw_host_enter(n: &mut NativeCpu, address: u64, skip: i32) -> i32 {
    let mut hooked = false;
    let stopped = callback(n, |c| {
        crate::decomp::NATIVE.fetch_add(1, Ordering::Relaxed);
        let code = CONFIG.get().unwrap().code.iter().find(|m| address >= m.base && address < m.base + m.text.len() as u64);
        if let Some(code) = code {
            if let Ok(i) = code.entries.binary_search(&address) {
                let offset = (address - code.base) as usize;
                let end = code.entries.get(i + 1).copied().unwrap_or(code.base + code.text.len() as u64);
                let size = (end - address) as usize;
                let bytes = unsafe { std::slice::from_raw_parts(c.process().memory.base().add(address as usize), size) };
                if bytes != &code.text[offset..offset + size] {
                    crate::decomp::fail(c.process(), json!({"kind":"changed-code","pc":address})); c.halt(); return;
                }
            } else { crate::decomp::missing(c, address); return; }
        } else { crate::decomp::missing(c, address); return; }
        if skip == 0 && c.process().hle.owns(address) { crate::hle::trampoline(c); hooked = true; }
    });
    if stopped != 0 { 2 } else { hooked as i32 }
}
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_call(n: &mut NativeCpu) -> i32 {
    callback(n, |c| {
        if c.process().hle.owns(c.pc) { crate::hle::trampoline(c); }
        else { crate::decomp::missing(c, c.pc); }
    })
}
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_svc(n: &mut NativeCpu, imm: u32, pc: u64) -> i32 {
    callback(n, |c| { c.pc = pc + 4; crate::horizon::svc(c, imm as u16); })
}
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_trap(n: &mut NativeCpu, kind: u32, imm: u32, pc: u64) -> i32 {
    callback(n, |c| {
        crate::decomp::fail(c.process(), json!({"kind":"unsupported-instruction","pc":pc,"trap_kind":kind,"immediate":imm}));
        c.halt();
    })
}
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_poll(n: &mut NativeCpu) -> i32 { callback(n, |c| { crate::sched::yield_now(c); }) }
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_ticks(n: &NativeCpu) -> u64 { unsafe { (*n.owner.cast::<Cpu>()).process().ticks() } }
#[unsafe(no_mangle)]
pub extern "C" fn sw_host_hle(n: &NativeCpu, pc: u64) -> i32 { unsafe { (*n.owner.cast::<Cpu>()).process().hle.owns(pc) as i32 } }

extern "C" fn startup(c: &mut Cpu) {
    let config = CONFIG.get().unwrap();
    if config.sdk_startup != 0 {
        // nn::init::Start initializes the OS thread before the SDK DSOs, then
        // initializes the application's heap before the main DSO and nnMain.
        let p = c.process();
        let sdk = p.hle.add("<native-sdk-initializers>", std::sync::Arc::new(|c| sdk_initializers(c, false)));
        let main = p.hle.add("<native-main-initializers>", std::sync::Arc::new(|c| sdk_initializers(c, true)));
        c.x[0] = crate::horizon::MAIN_THREAD_HANDLE; c.x[1] = 0; c.x[2] = sdk; c.x[3] = main;
        c.x[30] = HALT_PC; c.pc = config.sdk_startup;
        crate::process::call_indirect(c, HALT_PC);
        *crate::decomp::FINAL_CPU.lock().unwrap() = Some(json!({"x":c.x, "v":c.v,"nzcv":c.nzcv,"sp":c.sp,"pc":c.pc}));
        return;
    }
    for &address in &config.initializers {
        c.x[30] = HALT_PC; c.pc = address;
        crate::process::call_indirect(c, HALT_PC);
        if c.halted { return; }
        crate::decomp::INITIALIZERS.fetch_add(1, Ordering::Relaxed);
    }
    c.x[0] = 0; c.x[1] = crate::horizon::MAIN_THREAD_HANDLE;
    c.x[30] = HALT_PC; c.pc = config.entry;
    crate::process::call_indirect(c, HALT_PC);
    *crate::decomp::FINAL_CPU.lock().unwrap() = Some(json!({"x":c.x, "v":c.v,"nzcv":c.nzcv,"sp":c.sp,"pc":c.pc}));
}

fn sdk_initializers(c: &mut Cpu, main: bool) {
    let config = CONFIG.get().unwrap();
    let addresses = if main { &config.main_initializers } else { &config.sdk_initializers };
    for &address in addresses {
        crate::hle::call_guest(c, address, false);
        if c.halted { return; }
        crate::decomp::INITIALIZERS.fetch_add(1, Ordering::Relaxed);
    }
    c.pc = c.x[30];
}

unsafe fn text(pointer: *const c_char) -> String { unsafe { CStr::from_ptr(pointer) }.to_string_lossy().into_owned() }
fn load(assets: &std::path::Path) -> Result<(kirikae_loader::Executable, &'static [Entry]), String> {
    use kirikae_loader::{Executable, Module, Image};
    let mut modules = Vec::new(); let mut entries = Vec::new(); let mut code = Vec::new(); let mut samples = Vec::new();
    let count = unsafe { sw_module_count() };
    if count == 0 || count > 32 { return Err("invalid native module count".into()); }
    for i in 0..count {
        let m = unsafe { &*sw_module_at(i) };
        let name = unsafe { text(m.name) }; let file = assets.join(unsafe { text(m.file) });
        let path = CString::new(file.to_string_lossy().as_bytes()).map_err(|e| e.to_string())?;
        if unsafe { switch_asset_matches_expected(path.as_ptr(), m.sha256) } != 1 { return Err(format!("asset identity differs: {}", file.display())); }
        let memory = std::fs::read(&file).map_err(|e| e.to_string())?;
        if memory.len() as u64 != m.size { return Err("native image size differs".into()); }
        let addresses = unsafe { std::slice::from_raw_parts(m.addresses, *m.count as usize) };
        if !addresses.windows(2).all(|p| p[0] < p[1]) { return Err("unsorted native function table".into()); }
        entries.extend(addresses.iter().map(|&addr| Entry { addr, func: entry }));
        let start = m.text_offset as usize; let end = start + m.text_size as usize;
        code.push(Code { base: m.base + m.text_offset, text: memory[start..end].to_vec(), entries: addresses.to_vec() });
        let range = |offset: u64, size: u64| m.base + offset..m.base + offset + size;
        samples.push((name.clone(), m.base + m.data_offset, m.data_size.min(256)));
        modules.push(Module { name, image: Image { base: m.base, entry: m.base,
            text: range(m.text_offset, m.text_size), ro: range(m.ro_offset, m.ro_size),
            data: range(m.data_offset, m.data_size), bss: range(m.data_offset + m.data_size, m.bss_size), memory } });
    }
    let mut n = 0;
    let initializers = unsafe { std::slice::from_raw_parts(sw_initializers(&mut n), n) }.to_vec();
    let mut n = 0;
    let sdk_initializers = unsafe { std::slice::from_raw_parts(sw_sdk_initializers(&mut n), n) }.to_vec();
    let main_initializers = unsafe { std::slice::from_raw_parts(sw_main_initializers(&mut n), n) }.to_vec();
    let config = Config { code, initializers, entry: unsafe { sw_entry() }, samples,
        sdk_startup: unsafe { sw_sdk_startup() }, sdk_initializers, main_initializers };
    CONFIG.set(config).map_err(|_| "one game per native process".to_string())?;
    entries.push(Entry { addr: STARTUP, func: startup }); entries.sort_by_key(|e| e.addr);
    if !entries.windows(2).all(|p| p[0].addr < p[1].addr) { return Err("overlapping native entry addresses".into()); }
    unsafe { sw_initialize(); }
    let romfs_hash = unsafe { text(sw_romfs_sha256()) };
    let romfs = if !romfs_hash.is_empty() {
        let path = assets.join("romfs.bin");
        let raw = CString::new(path.to_string_lossy().as_bytes()).map_err(|e| e.to_string())?;
        if unsafe { switch_asset_matches_expected(raw.as_ptr(), sw_romfs_sha256()) } != 1 { return Err("RomFS identity differs".into()); }
        let image = kirikae_loader::RomFs { size: path.metadata().map_err(|e| e.to_string())?.len(), path, offset: 0, compression: None };
        kirikae_loader::romfs::Reader::open(&image).map_err(|e| format!("invalid RomFS: {e}"))?;
        Some(image)
    } else { None };
    Ok((Executable { modules, entry: STARTUP, title_id: Some(unsafe { sw_title_id() }),
        main_stack_size: Some(unsafe { sw_stack_size() }), romfs, ..Default::default() }, Box::leak(entries.into_boxed_slice())))
}

fn run(args: &[String]) -> Result<(i32, Value), String> {
    let mut assets = PathBuf::from("assets"); let mut renderer = "auto".to_string();
    let mut headless = false; let mut frames = 0; let mut saves = None;
    let mut i = 1;
    while i < args.len() {
        let next = |i: usize| args.get(i + 1).ok_or_else(|| "missing argument value".to_string());
        match args[i].as_str() {
            "--assets" => { assets = next(i)?.into(); i += 1; }
            "--renderer" => { renderer = next(i)?.clone(); i += 1; }
            "--frames" => { frames = next(i)?.parse::<u64>().map_err(|e| e.to_string())?; i += 1; }
            "--saves" => { saves = Some(next(i)?.clone()); i += 1; }
            "--report" => { next(i)?; i += 1; }
            "--headless" => headless = true,
            _ => return Err(format!("unknown native player option: {}", args[i])),
        }
        i += 1;
    }
    if !["auto", "vulkan", "software"].contains(&renderer.as_str()) { return Err("renderer must be auto, vulkan or software".into()); }
    // Set runtime options before starting any guest/display/audio threads.
    unsafe {
        std::env::remove_var("KIRIKAE_NO_VULKAN");
        std::env::remove_var("KIRIKAE_DRAW_PARTIAL");
        std::env::remove_var("KIRIKAE_SKIP_SHADER");
        std::env::set_var("DECOMP_SWITCH_RENDERER", &renderer);
        std::env::set_var("KIRIKAE_STRICT_IPC", "1");
        if headless { std::env::set_var("KIRIKAE_HEADLESS", "1"); }
        if let Some(path) = saves { std::env::set_var("KIRIKAE_SAVES", path); }
    }
    crate::decomp::FRAME_LIMIT.store(frames, Ordering::Relaxed);
    crate::decomp::ENABLED.store(true, Ordering::Relaxed);
    let (exe, entries) = load(&assets)?;
    let result = crate::process::run_executable(&exe, entries, crate::process::RunOptions { capture_output: false })?;
    let failures = crate::decomp::FAILURES.lock().unwrap().clone();
    let renderer_actual = crate::decomp::RENDERER.lock().unwrap().clone();
    let size = crate::display::window_size();
    let samples: Vec<Value> = CONFIG.get().unwrap().samples.iter().map(|(name, address, size)| {
        let bytes = crate::decomp::PROCESS.get().and_then(|p| p.memory.read(*address, *size)).unwrap_or_default();
        json!({"module":name,"address":address,"hex":bytes.iter().map(|v| format!("{v:02x}")).collect::<String>()})
    }).collect();
    let report = json!({"schema":"decomp.wtf.switch-native-run/v1", "platform":"switch", "output_kind":"cpu-probe",
        "input_sha256":unsafe { text(sw_input_sha256()) }, "backend_revision":unsafe { text(sw_backend_revision()) },
        "status":if result.exit_code == 0 && failures.is_empty() { "passed" } else { "failed" },
        "exit_code":result.exit_code, "interpreter_instructions":result.interpreted, "runtime_compilation":false,
        "host_action":if crate::decomp_host_menu::RETURNED_TO_SETTINGS.load(Ordering::Relaxed) { Some("settings") } else { None },
        "native_function_entries":crate::decomp::NATIVE.load(Ordering::Relaxed), "failures":failures,
        "final_cpu":crate::decomp::FINAL_CPU.lock().unwrap().clone(),"data_samples":samples,
        "graphics":crate::decomp::GPU.lock().unwrap().clone(),"audio":crate::decomp::AUDIO.lock().unwrap().clone(),
        "initializers_run":crate::decomp::INITIALIZERS.load(Ordering::Relaxed),
        "renderer_requested":renderer, "renderer_device":renderer_actual, "drawable":size,
        "frames":crate::display::FRAMES.load(Ordering::Relaxed), "headless":headless,
        "retail_qualification":false});
    Ok((result.exit_code, report))
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn switch_native_main(argc: i32, argv: *const *const c_char) -> i32 {
    let args: Vec<String> = (0..argc.max(0) as usize).map(|i| unsafe { text(*argv.add(i)) }).collect();
    let report = args.windows(2).find(|w| w[0] == "--report").map(|w| PathBuf::from(&w[1])).unwrap_or_else(|| "run-report.json".into());
    let _ = REPORT.set(report.clone());
    let (code, result) = match run(&args) {
        Ok(result) => result,
        Err(error) => (2, json!({"schema":"decomp.wtf.switch-native-run/v1","status":"failed","error":error,
            "input_sha256":unsafe { text(sw_input_sha256()) }, "backend_revision":unsafe { text(sw_backend_revision()) },
            "native_function_entries":crate::decomp::NATIVE.load(Ordering::Relaxed),
            "interpreter_instructions":0,"runtime_compilation":false})),
    };
    if let Err(error) = std::fs::write(&report, serde_json::to_vec_pretty(&result).unwrap()) {
        eprintln!("decomp.wtf: cannot write execution report: {error}"); return 3;
    }
    if code != 0 { eprintln!("decomp.wtf: execution stopped; see {}", report.display()); }
    code
}

// Preserve a report when the donor's guest-fault handler exits the process.
pub fn fatal_fault(address: u64) {
    if let Some(path) = REPORT.get() {
        let report = json!({"schema":"decomp.wtf.switch-native-run/v1", "status":"failed", "exit_code":4,
            "input_sha256":unsafe { text(sw_input_sha256()) }, "backend_revision":unsafe { text(sw_backend_revision()) },
            "interpreter_instructions":0, "runtime_compilation":false,
            "failures":[{"kind":"guest-memory-fault","address":address}]});
        let _ = std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap());
    }
}
