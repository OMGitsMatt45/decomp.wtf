"""Checked adaptations of the pinned donors; originals remain unchanged."""
from pathlib import Path


def replace_once(path, old, new):
    path = Path(path)
    source = path.read_text()
    if source.count(old) != 1:
        raise ValueError('Switch desktop patch no longer applies: ' + str(path))
    path.write_text(source.replace(old, new), encoding='utf-8', newline='\n')


def lifter(root):
    """Spill before cooperative scheduling, and use the runtime guest reservation."""
    root = Path(root)
    path = root / 'src/module.rs'
    old = '        lines.push(Line { label: s.labels.contains(&a).then_some(a), code, next: !last_ends });'
    new = '''        if s.labels.contains(&a) {
            lines.push(Line { label: Some(a),
                code: format!("(void)c->nzcv; SPILL c->pc = {}; sw_poll(c); RELOAD ", hx(a)), next: true });
        }
        lines.push(Line { label: None, code, next: !last_ends });'''
    replace_once(path, old, new)
    cpu = root / 'runtime/cpu.h'
    replace_once(cpu, '#include <string.h>', '''#include <string.h>
extern __thread uintptr_t sw_guest_memory_base;
#define SW_ADDRESS(a) (sw_guest_memory_base + ((uint64_t)(a) & 0x7fffffffffull))
struct Cpu;
void sw_poll(struct Cpu *c);''')
    for path in (cpu, root / 'runtime/simd.h'):
        text = path.read_text()
        if '(uintptr_t)(a)' not in text:
            raise ValueError('Switch C memory ABI patch no longer applies')
        text = text.replace('(uintptr_t)(a)', 'SW_ADDRESS(a)').replace('(uintptr_t)a', 'SW_ADDRESS(a)')
        path.write_text(text, encoding='utf-8', newline='\n')


def runtime(root, adapter):
    root, adapter = Path(root), Path(adapter)
    rt = root / 'crates/rt'
    replace_once(rt / 'src/lib.rs', 'pub mod interp;', '''#[cfg(feature = "diagnostic-interpreter")]
pub mod interp;
pub mod decomp;
#[cfg(feature = "decomp-native")]
pub mod decomp_native;
#[cfg(all(feature = "decomp-native", feature = "diagnostic-interpreter"))]
compile_error!("Native exports cannot include the guest CPU interpreter");''')
    manifest = rt / 'Cargo.toml'
    text = manifest.read_text() + '\n[lib]\ncrate-type = ["rlib", "staticlib"]\n'
    text = text.replace('[features]', '[features]\ndecomp-native = []\ndiagnostic-interpreter = []')
    manifest.write_text(text)
    replace_once(rt / 'src/process.rs', '''                entering = false;
                crate::interp::step(c);
                if c.pc <= pc && c.poll() {
                    break;
                }''', '''                #[cfg(feature = "diagnostic-interpreter")]
                {
                    entering = false;
                    crate::interp::step(c);
                    if c.pc <= pc && c.poll() { break; }
                }
                #[cfg(not(feature = "diagnostic-interpreter"))]
                { crate::decomp::missing(c, pc); break; }''')
    replace_once(rt / 'src/process.rs', '    pub(crate) interp_cache:',
                 '    #[cfg(feature = "diagnostic-interpreter")]\n    pub(crate) interp_cache:')
    replace_once(rt / 'src/process.rs', 'use kirikae_a64::Insn;',
                 '#[cfg(feature = "diagnostic-interpreter")]\nuse kirikae_a64::Insn;')
    replace_once(rt / 'src/process.rs', '        interp_cache: std::sync::RwLock::new(HashMap::new()),',
                 '        #[cfg(feature = "diagnostic-interpreter")]\n        interp_cache: std::sync::RwLock::new(HashMap::new()),')
    replace_once(rt / 'src/process.rs', '''        Some(self.entries[i].func)
    }

    pub fn symbol''', '''        #[cfg(feature = "decomp-native")]
        { let _ = i; Some(crate::decomp_native::unhooked) }
        #[cfg(not(feature = "decomp-native"))]
        { Some(self.entries[i].func) }
    }

    pub fn symbol''')
    replace_once(rt / 'src/process.rs', '    crate::nvn::install(process);',
                 '    crate::decomp::process_started(process);\n    crate::nvn::install(process);')
    # Track unsupported service paths even with the optional coverage recorder off.
    replace_once(rt / 'src/usage.rs', '''pub fn begin_ipc() {
    if on()''', '''pub fn begin_ipc() {
    CALL.with(|s| s.set((Status::Implemented, "")));
    if on()''')
    replace_once(rt / 'src/usage.rs', '''pub fn mark_stub(note: &'static str) {
    if on()''', '''pub fn mark_stub(note: &'static str) {
    CALL.with(|s| s.set((Status::Stub, note)));
    if on()''')
    replace_once(rt / 'src/usage.rs', '''pub fn end_ipc(c: &Cpu, iface: &str, req: &crate::services::Request) {
    if !on()''', '''pub fn end_ipc(c: &Cpu, iface: &str, req: &crate::services::Request) {
    let (status, note) = CALL.with(|s| s.get());
    if status != Status::Implemented { crate::decomp::unsupported(c, "service", iface, req.cmd as u64, note); }
    if !on()''')
    replace_once(rt / 'src/usage.rs', '''pub fn svc_missing(c: &Cpu, imm: u16) {
    if on()''', '''pub fn svc_missing(c: &Cpu, imm: u16) {
    crate::decomp::unsupported(c, "svc", "Horizon", imm as u64, "unimplemented SVC");
    if on()''')
    replace_once(rt / 'src/usage.rs', '''pub fn ioctl(c: &Cpu, device: &str, cmd: u32, handled: bool, args: &[u8]) {
    if on()''', '''pub fn ioctl(c: &Cpu, device: &str, cmd: u32, handled: bool, args: &[u8]) {
    if !handled { crate::decomp::unsupported(c, "ioctl", device, cmd as u64, "unimplemented ioctl"); }
    if on()''')
    replace_once(rt / 'src/usage.rs', '''pub fn shader(va: u64, mnemonics: &[(&'static str, u32)], unsupported: &[&'static str]) {
    if !on()''', '''pub fn shader(va: u64, mnemonics: &[(&'static str, u32)], unsupported: &[&'static str]) {
    if !unsupported.is_empty() { crate::decomp::gpu_failure(va, &unsupported.join(", ")); }
    if !on()''')
    replace_once(rt / 'src/gpu/mod.rs', '''                        eprintln!("kirikae: rendering with Vulkan on {}", r.name);''',
                 '''                        crate::decomp::renderer_started(&r.name, r.software);
                        eprintln!("kirikae: rendering with Vulkan on {}", r.name);''')
    replace_once(rt / 'src/gpu/mod.rs', '''                    Err(e) => eprintln!("kirikae: Vulkan is not available ({e}); draws are not rendered"),''',
                 '''                    Err(e) => { crate::decomp::gpu_failure(0, &e); eprintln!("decomp.wtf: Vulkan could not start ({e})"); },''')
    replace_once(rt / 'src/gpu/mod.rs', '    pub fn shutdown(&self) {\n        let mut guard = self.renderer.lock().unwrap();',
                 '    pub fn shutdown(&self) {\n        let mut guard = self.renderer.lock().unwrap();\n        crate::decomp::graphics_finished(self, guard.0.as_ref());')
    replace_once(rt / 'src/services/audio/output.rs', '        let device = rx.recv().map_err(|e| e.to_string())??;',
                 '        let result = rx.recv().map_err(|e| e.to_string())?;\n        crate::decomp::audio_opened(&result);\n        let device = result?;')
    replace_once(rt / 'src/gpu/vulkan/draw.rs', '        if let Err(why) = &ok {\n            self.stats.skipped += 1;',
                 '        if let Err(why) = &ok {\n            crate::decomp::gpu_failure(0, why);\n            self.stats.skipped += 1;')
    replace_once(rt / 'src/gpu/vulkan/draw.rs', '                self.stats.skipped_dispatches += 1;',
                 '                crate::decomp::gpu_failure(0, why);\n                self.stats.skipped_dispatches += 1;')
    # Native exports must preserve every draw, including transient targets on
    # the first use of a shader pair. Pending compilation is not a failed draw.
    replace_once(rt / 'src/gpu/vulkan/pipeline.rs',
                 '    pub(super) fn pipeline(&mut self, key: &PipelineKey, now: bool) -> Result<vk::Pipeline, String> {',
                 '    pub(super) fn pipeline(&mut self, key: &PipelineKey, now: bool) -> Result<vk::Pipeline, String> {\n        let now = now || cfg!(feature = "decomp-native");')
    replace_once(rt / 'src/fault.rs', '    std::process::exit(4);',
                 '    #[cfg(feature = "decomp-native")]\n    crate::decomp_native::fatal_fault(guest);\n    std::process::exit(4);')
    vk = rt / 'src/gpu/vulkan/mod.rs'
    replace_once(vk, '    pub name: String,', '    pub name: String,\n    pub software: bool,')
    replace_once(vk, '            name,\n            stats:', '            name,\n            software: props.device_type == vk::PhysicalDeviceType::CPU,\n            stats:')
    replace_once(vk, '        let devices = unsafe { instance.enumerate_physical_devices()? };',
                 '        let software_only = std::env::var("DECOMP_SWITCH_RENDERER").as_deref() == Ok("software");\n        let devices = unsafe { instance.enumerate_physical_devices()? };')
    replace_once(vk, '            .max_by_key(|&d| match unsafe { instance.get_physical_device_properties(d) }.device_type {',
                 '            .filter(|&d| !software_only || unsafe { instance.get_physical_device_properties(d) }.device_type == vk::PhysicalDeviceType::CPU)\n            .max_by_key(|&d| match unsafe { instance.get_physical_device_properties(d) }.device_type {')
    display = rt / 'src/display.rs'
    replace_once(display, '    note_frame();\n    if n == 1 {\n        p.warn_once("display: first frame presented (Vulkan swapchain)"',
                 '    note_frame();\n    crate::decomp::presented(p);\n    if n == 1 {\n        p.warn_once("display: first frame presented (Vulkan swapchain)"')
    replace_once(display, '    note_frame();\n    if n == 1 {\n        p.warn_once(format!("display: first frame presented ({}x{})"',
                 '    note_frame();\n    crate::decomp::presented(p);\n    if n == 1 {\n        p.warn_once(format!("display: first frame presented ({}x{})"')
    replace_once(display, '        let attrs = Window::default_attributes().with_title(&self.title).with_inner_size(LogicalSize::new(1280.0, 720.0));',
                 '        let mut attrs = Window::default_attributes().with_title(&self.title).with_inner_size(LogicalSize::new(1280.0, 720.0));\n        if let Some(monitor) = el.primary_monitor().or_else(|| el.available_monitors().next()) {\n            let size = monitor.size();\n            attrs = attrs.with_inner_size(size).with_position(monitor.position());\n        }')
    replace_once(display, '                    crate::input::key(code, event.state.is_pressed());',
                 '                    if code == winit::keyboard::KeyCode::F11 && event.state.is_pressed() && !event.repeat {\n                        if let Some(w) = &self.window {\n                            let mode = if w.fullscreen().is_some() { None } else { Some(winit::window::Fullscreen::Borderless(w.current_monitor())) };\n                            w.set_fullscreen(mode);\n                        }\n                    } else { crate::input::key(code, event.state.is_pressed()); }')
    replace_once(rt / 'src/process.rs', 'while s.live.load(Ordering::Relaxed) > 0 && !s.exiting.load(Ordering::Relaxed) {',
                 'while s.live.load(Ordering::Relaxed) > 0 {')
    replace_once(rt / 'src/services/fs.rs', 'base.join("kirikae").join("saves")',
                 'base.join("decomp.wtf").join("switch").join("saves")')
    replace_once(rt / 'src/input.rs', 'pub fn key(code: KeyCode, pressed: bool) {',
                 'pub fn key(code: KeyCode, pressed: bool) {\n    if crate::env_var!("KIRIKAE_INPUT_TRACE").is_some() { eprintln!("kirikae: input key {code:?} pressed={pressed}"); }')
    replace_once(rt / 'src/sched.rs', '        if d.is_zero() { std::thread::yield_now() } else { std::thread::sleep(d) }',
                 '        if d.is_zero() { std::thread::yield_now() } else {\n            let start = std::time::Instant::now();\n            while start.elapsed() < d && !c.process().sched.exiting.load(Ordering::Relaxed) {\n                std::thread::sleep((d - start.elapsed().min(d)).min(Duration::from_millis(10)));\n            }\n        }')
    for name in ('decomp.rs', 'decomp_native.rs'):
        (rt / 'src' / name).write_bytes((adapter / name).read_bytes())
    from .services import applet_controls, parental_session, hid_activation, applet_audio, hid_vibration, hid_sensors, keyboard_edges
    applet_controls(root, adapter)
    parental_session(root)
    hid_activation(root)
    applet_audio(root)
    hid_vibration(root, adapter)
    hid_sensors(root, adapter)
    keyboard_edges(root)
    (rt / 'examples').mkdir(exist_ok=True)
    (rt / 'examples/decomp-graphics.rs').write_bytes((adapter / 'graphics_probe.rs').read_bytes())
