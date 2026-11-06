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
    replace_once(manifest, 'vp9dec = "=0.1.1"',
                 'oxideav-vp8 = { version = "=0.2.7", default-features = false }\nvp9dec = "=0.1.1"')
    from .video import vp8
    vp8(rt, adapter)
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
    # Map the Maxwell window origin and its independent Y flip to the host
    # front-face convention. Vulkan applies the signed viewport separately.
    replace_once(rt / 'src/gpu/vulkan/draw.rs',
                 '            let front = if regs[0x647] != 0x900 { vk::FrontFace::COUNTER_CLOCKWISE } else { vk::FrontFace::CLOCKWISE };',
                 '''            let origin = regs[0x4eb];
            let clockwise = (regs[0x647] == 0x900) ^ (origin & 1 == 0) ^ (origin & 0x10 != 0);
            let front = if clockwise { vk::FrontFace::CLOCKWISE } else { vk::FrontFace::COUNTER_CLOCKWISE };''')
    # Maxwell's A1B5G5R5 (TIC 0x14) has red in the low five bits.
    # Keep the Vulkan A1R5G5B5 image and translate the guest's component selectors.
    replace_once(rt / 'src/gpu/vulkan/textures.rs',
                 '''    header.swizzle.map(|s| match s {
        0 => vk::ComponentSwizzle::ZERO,
        2 => vk::ComponentSwizzle::R,
        3 => vk::ComponentSwizzle::G,
        4 => vk::ComponentSwizzle::B,''',
                 '''    use vk::ComponentSwizzle as S;
    let (red, blue) = if header.components == 0x14 { (S::B, S::R) } else { (S::R, S::B) };
    header.swizzle.map(|s| match s {
        0 => S::ZERO,
        2 => red,
        3 => S::G,
        4 => blue,''')
    replace_once(rt / 'src/gpu/vulkan/textures.rs',
                 'pub(super) fn read_texture(gpu: &Gpu,',
                 '''#[cfg(test)]
#[test]
fn a1b5g5r5_translates_component_selectors() {
    use vk::ComponentSwizzle as S;
    let mut words = [0; 8];
    words[0] = 0x14 | 2 << 19 | 3 << 22 | 4 << 25 | 5 << 28;
    let mut header = crate::gpu::tic::texture_header(&words);
    assert_eq!(swizzle(&header), [S::B, S::G, S::R, S::A]);
    header.swizzle = [4, 0, 2, 7];
    assert_eq!(swizzle(&header), [S::R, S::ZERO, S::B, S::ONE]);
    header.components = 0x08;
    assert_eq!(swizzle(&header), [S::B, S::ZERO, S::R, S::ONE]);
}

pub(super) fn read_texture(gpu: &Gpu,''')
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
                 '        let attrs = crate::decomp_host_window::attributes(el, &self.title);')
    replace_once(display, 'use winit::dpi::LogicalSize;\n', '')
    replace_once(display, '                    crate::input::key(code, event.state.is_pressed());',
                 '''                    if code == winit::keyboard::KeyCode::F10 && event.state.is_pressed() && !event.repeat {
                        if crate::decomp_host_menu::confirm() {
                            self.p.terminate(0);
                            self.p.gpu.shutdown();
                            el.exit();
                        }
                    } else if code == winit::keyboard::KeyCode::F11 && event.state.is_pressed() && !event.repeat {
                        if let Some(w) = &self.window {
                            let mode = if w.fullscreen().is_some() { None } else { Some(winit::window::Fullscreen::Borderless(w.current_monitor())) };
                            w.set_fullscreen(mode);
                        }
                    } else { crate::input::key(code, event.state.is_pressed()); }''')
    replace_once(rt / 'src/lib.rs', 'pub mod display;', 'pub mod display;\nmod decomp_host_menu;')
    (rt / 'src/decomp_host_menu.rs').write_bytes((adapter / 'host_menu.rs').read_bytes())
    replace_once(rt / 'src/lib.rs', 'mod decomp_host_menu;', 'mod decomp_host_menu;\nmod decomp_host_window;')
    (rt / 'src/decomp_host_window.rs').write_bytes((adapter / 'host_window.rs').read_bytes())
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
    from .services import (account_availability, applet_controls, application_play_history,
                           parental_session, hid_activation, applet_audio, hid_vibration,
                           hid_idle_states, hid_sensors, keyboard_edges)
    account_availability(root)
    application_play_history(root)
    applet_controls(root, adapter)
    parental_session(root)
    hid_activation(root)
    applet_audio(root)
    hid_vibration(root, adapter)
    hid_sensors(root, adapter)
    hid_idle_states(root)
    keyboard_edges(root)
    services = rt / 'src/services/mod.rs'
    replace_once(services, 'pub mod stub;', 'pub mod stub;\nmod decomp_bsd;\nmod decomp_play_report;')
    replace_once(services, '        "lm" => Arc::new(lm::Lm),',
                 '        "lm" => Arc::new(lm::Lm),\n        "bsd:u" => Arc::new(decomp_bsd::OfflineBsd),\n        "prepo:u" => Arc::new(decomp_play_report::PlayReport),')
    (rt / 'src/services/decomp_bsd.rs').write_bytes((adapter / 'bsd_offline.rs').read_bytes())
    (rt / 'src/services/decomp_play_report.rs').write_bytes((adapter / 'play_report.rs').read_bytes())
    from .keyboard import apply as software_keyboard
    software_keyboard(root, adapter)
    (rt / 'examples').mkdir(exist_ok=True)
    (rt / 'examples/decomp-graphics.rs').write_bytes((adapter / 'graphics_probe.rs').read_bytes())
    from .graphics import integer_textures
    integer_textures(root)
    from .bindless import apply as static_bindless_textures
    static_bindless_textures(root)
    from .presentation import buffer_crop
    buffer_crop(root)
    from .sample_grid import apply as maxwell_sample_grid
    maxwell_sample_grid(root)
