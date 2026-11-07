//! Source-export integration: strict coverage, observable renderer and run limits.
use std::sync::{Mutex, OnceLock};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use serde_json::{Value, json};
use crate::{Cpu, process::Process};

pub static PROCESS: OnceLock<&'static Process> = OnceLock::new();
pub static NATIVE: AtomicU64 = AtomicU64::new(0);
pub static ENABLED: AtomicBool = AtomicBool::new(false);
pub static INITIALIZERS: AtomicU64 = AtomicU64::new(0);
pub static FRAME_LIMIT: AtomicU64 = AtomicU64::new(0);
pub static FAILURES: Mutex<Vec<Value>> = Mutex::new(Vec::new());
pub static RENDERER: Mutex<Option<Value>> = Mutex::new(None);
pub static FINAL_CPU: Mutex<Option<Value>> = Mutex::new(None);
pub static GPU: Mutex<Option<Value>> = Mutex::new(None);
pub static AUDIO: Mutex<Option<Value>> = Mutex::new(None);

pub fn graphics_finished(g: &crate::gpu::Gpu, r: Option<&crate::gpu::vulkan::Renderer>) {
    if let Some(r) = r {
        if r.stats.checked_pending_reused != 0 || r.stats.checked_pending_scans != 0 {
            eprintln!("kirikae: checked pending ranges: {} proofs reused, {} exact scans",
                r.stats.checked_pending_reused, r.stats.checked_pending_scans);
        }
        *GPU.lock().unwrap() = Some(json!({"submits":g.stats.submits.load(Ordering::Relaxed),
            "draws":r.stats.draws,"skipped_draws":r.stats.skipped,"dispatches":r.stats.dispatches,
            "skipped_dispatches":r.stats.skipped_dispatches,"skip_reasons":r.stats.skip_reasons}));
    }
}
pub fn audio_opened(result: &Result<String, String>) {
    *AUDIO.lock().unwrap() = Some(match result {
        Ok(device) => json!({"status":"opened","device":device}),
        Err(error) => json!({"status":"failed","error":error}),
    });
    if let Err(error) = result {
        if let Some(p) = PROCESS.get() { fail(p, json!({"kind":"audio","error":error})); }
    }
}

pub fn process_started(p: &'static Process) { let _ = PROCESS.set(p); }
pub fn fail(p: &Process, event: Value) {
    if !ENABLED.load(Ordering::Relaxed) { return; }
    let mut events = FAILURES.lock().unwrap();
    if events.len() < 128 { events.push(event); }
    drop(events);
    p.terminate(2);
}
pub fn missing(c: &mut Cpu, pc: u64) {
    crate::coverage::record(pc);
    fail(c.process(), json!({"kind":"missing-native-target","pc":pc,"thread":c.thread.id}));
    c.halt();
}
pub fn unsupported(c: &Cpu, kind: &str, interface: &str, command: u64, note: &str) {
    fail(c.process(), json!({"kind":kind,"interface":interface,"command":command,"note":note,"pc":c.pc}));
}
pub fn gpu_failure(address: u64, message: &str) {
    if let Some(p) = PROCESS.get() { fail(p, json!({"kind":"graphics","address":address,"message":message})); }
}
pub fn renderer_started(name: &str, software: bool) {
    *RENDERER.lock().unwrap() = Some(json!({"api":"vulkan","device":name,"software":software,
        "software_fallback_reported":software,"fallback_reason":if software { "Vulkan CPU device" } else { "" }}));
}
pub fn presented(p: &Process) {
    let limit = FRAME_LIMIT.load(Ordering::Relaxed);
    if limit != 0 && crate::display::FRAMES.load(Ordering::Relaxed) >= limit { p.terminate(0); }
}
