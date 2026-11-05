"""Checked service adaptations on a copied, pinned Switch runtime."""
from pathlib import Path


def applet_controls(root, adapter):
    from .patches import replace_once
    root, adapter = Path(root), Path(adapter)
    am = root / 'crates/rt/src/services/am'
    replace_once(am / 'mod.rs', 'mod applet;', 'mod applet;\nmod decomp_control;')
    (am / 'decomp_control.rs').write_bytes((adapter / 'applet_control.rs').read_bytes())
    replace_once(am / 'state.rs', 'pub struct AmState {',
                 'pub struct AmState {\n    pub(super) controls: Mutex<super::decomp_control::ControlState>,')
    replace_once(am / 'applet.rs', '                let state = Arc::new(AmState {',
                 '                let state = Arc::new(AmState {\n                    controls: Mutex::new(Default::default()),')
    replace_once(am / 'applet.rs', '            1 => Arc::new(SelfController),',
                 '            1 => Arc::new(SelfController { state: self.state.clone() }),')
    replace_once(am / 'applet.rs', 'struct SelfController;', 'struct SelfController { state: Arc<AmState> }')
    prefix = '''impl Service for SelfController {
    fn name(&self) -> String {
        "am/ISelfController".into()
    }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
'''
    replace_once(am / 'applet.rs', prefix, prefix + '''        if let Some(result) = self.state.controls.lock().unwrap().apply(req.cmd, &req.data) {
            return if result == 0 { Reply::ok() } else { Reply::err(result) };
        }
''')
    replace_once(am / 'applet.rs', '            19 => Reply::ok(),',
                 '            19 => unimplemented("am/ISelfController", c, req),')
    replace_once(am / 'applet.rs', '            let reply = SelfController.call(', '''            let service = SelfController { state: Arc::new(AmState {
                controls: Mutex::new(Default::default()), messages: Mutex::new(VecDeque::new()),
                message_event: c.process().create_event(false), user_popped: AtomicBool::new(false),
            }) };
            let reply = service.call(''')


def application_play_history(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/services/am/applet.rs'
    replace_once(path, '            50 => Reply::ok().bytes(&[0x44; 16]),',
                 '''            50 => Reply::ok().bytes(&[0x44; 16]),
            // QueryApplicationPlayStatisticsByUid. This host has no imported
            // console play log, so there are zero entries in the output buffer.
            111 if req.data.len() >= 16 && req.a.len() == 1 && req.b.len() == 1 => Reply::ok().u32(0),
            111 => Reply::err(super::storage::RESULT_INVALID_PARAMETERS),''')
    replace_once(path, '    #[test]\n    fn set_album_image_orientation_succeeds_with_no_output()', '''    #[test]
    fn local_application_play_history_returns_an_empty_count() {
        extern "C" fn probe(c: &mut Cpu) {
            let proxy = AppletOe.call(c, &Request::default());
            let functions = proxy.objects[0].call(c, &Request { cmd: 20, ..Default::default() });
            let functions = &functions.objects[0];
            let request = Request { cmd: 111, data: crate::services::acc::USER_ID.to_vec(),
                a: vec![crate::services::Buf { addr: 0, size: 8 }],
                b: vec![crate::services::Buf { addr: 0, size: 0x18 }], ..Default::default() };
            let valid = functions.call(c, &request);
            let invalid = functions.call(c, &Request { cmd: 111, ..Default::default() });
            harness::record("am/play_history", &[valid.result as u64,
                u32::from_le_bytes(valid.data.try_into().unwrap()) as u64, invalid.result as u64]);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
        assert_eq!(harness::observed("am/play_history"), vec![0, 0, super::super::storage::RESULT_INVALID_PARAMETERS as u64]);
    }

    #[test]
    fn set_album_image_orientation_succeeds_with_no_output()''')


def parental_session(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/services/pctl.rs'
    replace_once(path, 'use crate::services::stub::{unimplemented, Stub};',
                 'use crate::services::stub::unimplemented;')
    replace_once(path, 'Arc::new(Stub::new("pctl/IParentalControlService"))',
                 'Arc::new(ParentalSession { initialized: std::sync::atomic::AtomicBool::new(req.cmd == 0) })')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('''
// No console parental-control database is imported into this desktop session.
// Initializing the game-facing service does not change any host/account policy.
struct ParentalSession { initialized: std::sync::atomic::AtomicBool }
impl Service for ParentalSession {
    fn name(&self) -> String { "pctl/IParentalControlService".into() }
    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        use std::sync::atomic::Ordering;
        if req.cmd == 1 {
            self.initialized.store(true, Ordering::Relaxed);
            return Reply::ok();
        }
        if self.initialized.load(Ordering::Relaxed) {
            match req.cmd {
                1012 => return Reply::ok().u32(0),
                1031 => return Reply::ok().u8(0),
                _ => {},
            }
        }
        unimplemented("pctl/IParentalControlService", c, req)
    }
}

#[cfg(test)]
mod decomp_pctl_tests {
    use super::*;
    use crate::{abi::Entry, services::harness};
    #[test]
    fn game_facing_session_initializes_without_host_policy_changes() {
        extern "C" fn probe(c: &mut Cpu) {
            let factory = Pctl { name: "pctl" };
            let created = factory.call(c, &Request { cmd: 1, ..Default::default() });
            let session = created.objects[0].clone();
            let initialized = session.call(c, &Request { cmd: 1, ..Default::default() });
            let enabled = session.call(c, &Request { cmd: 1031, ..Default::default() });
            let features = session.call(c, &Request { cmd: 1012, ..Default::default() });
            harness::record("pctl/session", &[created.result as u64, initialized.result as u64,
                enabled.data[0] as u64, features.data.len() as u64]);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
        assert_eq!(harness::observed("pctl/session"), vec![0, 0, 0, 4]);
    }
}
''')


def account_availability(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/services/acc.rs'
    replace_once(path, 'Arc::new(crate::services::stub::Stub::new("acc/IManagerForApplication"))',
                 'Arc::new(ApplicationAccountManager)')
    replace_once(path, 'struct Profile;', '''struct ApplicationAccountManager;

impl Service for ApplicationAccountManager {
    fn name(&self) -> String { "acc/IManagerForApplication".into() }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        match req.cmd {
            // The local profile has no linked Nintendo account.
            0 => Reply::ok().u8(0),
            1 => Reply::ok().u64(0),
            _ => unimplemented("acc/IManagerForApplication", c, req),
        }
    }
}

#[cfg(test)]
#[test]
fn local_application_account_reports_offline() {
    use crate::{abi::Entry, services::harness};
    extern "C" fn probe(c: &mut Cpu) {
        let account = Account { name: "acc:u0" };
        let session = account.call(c, &Request { cmd: 101, data: USER_ID.to_vec(), ..Default::default() });
        let manager = &session.objects[0];
        let availability = manager.call(c, &Request::default());
        let id = manager.call(c, &Request { cmd: 1, ..Default::default() });
        harness::record("acc/availability", &[availability.result as u64, availability.data.len() as u64,
            availability.data[0] as u64, id.result as u64, u64::from_le_bytes(id.data.try_into().unwrap())]);
        c.halt();
    }
    harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
    assert_eq!(harness::observed("acc/availability"), vec![0, 1, 0, 0, 0]);
}

struct Profile;''')


def hid_activation(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/services/hid.rs'
    replace_once(path, 'const IDLE_LIFOS: [(u64, u64); 4] = [(0x0, 0x28), (0x400, 0x298), (0x3400, 0x30), (0x3800, 0x38)];',
                 'const IDLE_LIFOS: [(u64, u64); 5] = [(0x0, 0x28), (0x400, 0x298), (0x3400, 0x30), (0x3800, 0x38), (0x3ba00, 0x68)];')
    replace_once(path, 'struct Inner {', 'struct Inner {\n    active: bool,\n    revision: u32,\n    peripherals: u32,\n    palma_boost: bool,\n    palma_connectable: bool,\n    handheld_activation: u64,\n    assignments: [u32; 10],\n    disconnected: u32,')
    replace_once(path, 'fn wanted() -> Option<(usize, &\'static Style)> {',
                 '#[cfg(test)]\nfn wanted() -> Option<(usize, &\'static Style)> {')
    replace_once(path, '                write_header(write, i, Some(s));',
                 '                write_header(write, i, Some(s));\n                write(NPAD + i as u64 * NPAD_ENTRY + field::JOY_ASSIGNMENT_MODE, &st.assignments[i].to_le_bytes());')
    replace_once(path, '        let changed = self.update(&crate::input::state(), wanted(), &mut write);',
                 '''        let selected = {
            let state = self.inner.lock().unwrap();
            let ids = SUPPORTED_IDS.load(Relaxed);
            let ids = (if ids == 0 { !0 } else { ids }) & !state.disconnected;
            if state.active && ids != 0 { choose(SUPPORTED_STYLES.load(Relaxed), ids, prefer_handheld()) } else { None }
        };
        let changed = self.update(&crate::input::state(), selected, &mut write);''')
    replace_once(path, ' | 103 | 104 | 109 | 122', ' | 122')
    replace_once(path, ' | 128 | 129 | 130', ' | 130')
    replace_once(path, ' | 122 | 123 | 124 | 125', ' | 125')
    replace_once(path, '            1 | 11 | 21 | 31 | 40 |', '            40 |')
    replace_once(path, '            100 => {', '''            122 | 123 | 124 => {
                let Some(index) = npad_index(req.u32(0)) else { return unimplemented("hid", c, req); };
                let n = npads(c);
                let mode = if req.cmd == 124 { 0 } else { 1 };
                {
                    let mut state = n.inner.lock().unwrap();
                    if mode == 1 && state.connected.is_some_and(|(i, style)| i == index && style.tag == STYLE_JOY_DUAL) {
                        return unimplemented("hid", c, req);
                    }
                    state.assignments[index] = mode;
                }
                n.memory.write(&c.process().memory, NPAD + index as u64 * NPAD_ENTRY + field::JOY_ASSIGNMENT_MODE, &mode.to_le_bytes());
                Reply::ok()
            }
            128 => {
                let mode = req.u64(8);
                if mode > 2 { return unimplemented("hid", c, req); }
                let n = npads(c);
                n.inner.lock().unwrap().handheld_activation = mode;
                // The virtual handheld has both sides attached, satisfying
                // all three minimum-attached-controller policies.
                n.tick(c.process());
                Reply::ok()
            }
            129 => Reply::ok().u64(npads(c).inner.lock().unwrap().handheld_activation),
            522 | 525 | 527 => {
                let n = npads(c);
                let mut state = n.inner.lock().unwrap();
                if req.cmd == 522 { state.palma_connectable = req.u32(0) & 0xff != 0; }
                else { state.palma_boost = req.u32(0) & 0xff != 0; }
                Reply::ok()
            }
            103 | 109 => {
                let revision = if req.cmd == 109 { req.u32(0) } else { 0 };
                let n = npads(c);
                { let mut state = n.inner.lock().unwrap(); state.active = true; state.revision = revision; state.disconnected = 0; }
                n.tick(c.process());
                Reply::ok()
            }
            104 => {
                let n = npads(c);
                n.inner.lock().unwrap().active = false;
                n.tick(c.process());
                Reply::ok()
            }
            107 => {
                let Some(index) = npad_index(req.u32(0)) else { return unimplemented("hid", c, req); };
                let n = npads(c);
                n.inner.lock().unwrap().disconnected |= 1 << index;
                n.tick(c.process());
                Reply::ok()
            }
            1 | 11 | 21 | 31 | 91 => {
                let n = npads(c);
                let flag = match req.cmd { 1 => 1, 11 => 2, 21 => 4, 31 => 8, _ => 16 };
                n.inner.lock().unwrap().peripherals |= flag;
                // The existing idle LIFOs publish empty peripheral samples at
                // the HID cadence; activation starts/retains that publisher.
                n.tick(c.process());
                Reply::ok()
            }
            100 => {''')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('''
#[cfg(test)]
mod decomp_activation_tests {
    use super::*;
    use crate::{abi::Entry, services::harness};
    #[test]
    fn npad_activation_publishes_and_deactivation_disconnects() {
        extern "C" fn probe(c: &mut Cpu) {
            SUPPORTED_STYLES.store(STYLE_FULL_KEY, Relaxed); SUPPORTED_IDS.store(1, Relaxed);
            let n = npads(c);
            let before = n.inner.lock().unwrap().active;
            let activated = Hid.call(c, &Request { cmd: 109, data: 1u32.to_le_bytes().to_vec(), ..Default::default() });
            let (active, revision) = { let state = n.inner.lock().unwrap(); (state.active, state.revision) };
            let mut data = 0x60u64.to_le_bytes().to_vec(); data.extend_from_slice(&1u64.to_le_bytes());
            let set_mode = Hid.call(c, &Request { cmd: 128, data, ..Default::default() });
            let mode = Hid.call(c, &Request { cmd: 129, ..Default::default() });
            let mode = u64::from_le_bytes(mode.data[..8].try_into().unwrap());
            let connected_before = n.inner.lock().unwrap().connected.is_some();
            let disconnected = Hid.call(c, &Request { cmd: 107, data: 0u32.to_le_bytes().to_vec(), ..Default::default() });
            let connected_after = n.inner.lock().unwrap().connected.is_some();
            let reactivated = Hid.call(c, &Request { cmd: 103, ..Default::default() });
            let connected_again = n.inner.lock().unwrap().connected.is_some();
            let deactivated = Hid.call(c, &Request { cmd: 104, ..Default::default() });
            let state = n.inner.lock().unwrap();
            harness::record("hid/activation", &[before as u64, activated.result as u64, active as u64,
                revision as u64, deactivated.result as u64, state.active as u64, state.connected.is_none() as u64,
                set_mode.result as u64, mode, connected_before as u64, disconnected.result as u64,
                connected_after as u64, reactivated.result as u64, connected_again as u64]);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
        assert_eq!(harness::observed("hid/activation"), vec![0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0, 0, 0, 1]);
    }
}
''')


def applet_audio(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/services/am/applet.rs'
    replace_once(path, '            3 => stub("am/IAudioController"),', '            3 => Arc::new(AudioController),')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('''
// These expected volumes are saved/restored by applications around applets.
// They are session state, distinct from the renderer's voice/mix volumes.
struct AudioController;
impl Service for AudioController {
    fn name(&self) -> String { "am/IAudioController".into() }
    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
        let state = c.process().service_state("am.audio.expected", || Mutex::new([1.0f32, 1.0f32]));
        let mut volumes = state.lock().unwrap();
        match req.cmd {
            0 if req.data.len() >= 8 => {
                let main = f32::from_bits(req.u32(0));
                let library = f32::from_bits(req.u32(4));
                if main.is_finite() && library.is_finite() && (0.0..=1.0).contains(&main) && (0.0..=1.0).contains(&library) {
                    *volumes = [main, library];
                    Reply::ok()
                } else { unimplemented("am/IAudioController", c, req) }
            }
            1 | 2 => Reply::ok().u32(volumes[(req.cmd - 1) as usize].to_bits()),
            _ => unimplemented("am/IAudioController", c, req),
        }
    }
}

#[cfg(test)]
mod decomp_audio_tests {
    use super::*;
    use crate::abi::Entry;
    use crate::services::harness;
    #[test]
    fn expected_volumes_round_trip_as_independent_float_fields() {
        extern "C" fn probe(c: &mut Cpu) {
            let service = AudioController;
            let mut data = 0.25f32.to_le_bytes().to_vec(); data.extend_from_slice(&0.5f32.to_le_bytes());
            let set = service.call(c, &Request { cmd: 0, data, ..Default::default() });
            let main = service.call(c, &Request { cmd: 1, ..Default::default() });
            let library = service.call(c, &Request { cmd: 2, ..Default::default() });
            let decode = |reply: Reply| u32::from_le_bytes(reply.data[..4].try_into().unwrap()) as u64;
            harness::record("am/expected_volumes", &[set.result as u64, decode(main), decode(library)]);
            c.halt();
        }
        harness::run(vec![Entry { addr: harness::ENTRY, func: probe }]);
        assert_eq!(harness::observed("am/expected_volumes"), vec![0, 0.25f32.to_bits() as u64, 0.5f32.to_bits() as u64]);
    }
}
''')


def hid_vibration(root, adapter):
    from .patches import replace_once
    folder = Path(root) / 'crates/rt/src/services'
    (folder / 'hid').mkdir(exist_ok=True)
    (folder / 'hid/decomp_vibration.rs').write_bytes((Path(adapter) / 'vibration.rs').read_bytes())
    replace_once(folder / 'hid.rs', 'pub struct Hid;', 'mod decomp_vibration;\n\npub struct Hid;')
    prefix = '''impl Service for Hid {
    fn name(&self) -> String {
        "hid".into()
    }

    fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
'''
    replace_once(folder / 'hid.rs', prefix, prefix + '        if let Some(reply) = decomp_vibration::call(c, req) { return reply; }\n')


def hid_sensors(root, adapter):
    from .patches import replace_once
    folder = Path(root) / 'crates/rt/src/services'
    (folder / 'hid').mkdir(exist_ok=True)
    (folder / 'hid/decomp_sensors.rs').write_bytes((Path(adapter) / 'sensors.rs').read_bytes())
    replace_once(folder / 'hid.rs', 'pub struct Hid;', 'mod decomp_sensors;\n\npub struct Hid;')
    replace_once(folder / 'hid.rs', 'struct Inner {', 'struct Inner {\n    sensors: decomp_sensors::State,')
    replace_once(folder / 'hid.rs', '                let on = style.is_some_and(|s| s.six_axis.contains(&lifo));',
                 '                let on = style.is_some_and(|s| s.six_axis.contains(&lifo)) && st.sensors.running(i, lifo);')
    replace_once(folder / 'hid.rs', '        if let Some(reply) = decomp_vibration::call(c, req) { return reply; }',
                 '        if let Some(reply) = decomp_sensors::call(c, req) { return reply; }\n        if let Some(reply) = decomp_vibration::call(c, req) { return reply; }')


def keyboard_edges(root):
    from .patches import replace_once
    path = Path(root) / 'crates/rt/src/input.rs'
    replace_once(path, 'static KEYS: Mutex<Option<HashSet<KeyCode>>> = Mutex::new(None);', '''struct Tap { until: std::time::Instant, limit: std::time::Instant, frame: Option<u64> }
impl Tap {
    fn visible(&self, now: std::time::Instant, frame: Option<u64>) -> bool {
        self.until > now || (now < self.limit &&
            self.frame.zip(frame).is_some_and(|(start, current)| current.saturating_sub(start) < 2))
    }
}
#[derive(Default)]
struct Keys { held: HashSet<KeyCode>, taps: std::collections::HashMap<KeyCode, Tap> }
impl Keys {
    fn set(&mut self, code: KeyCode, pressed: bool, now: std::time::Instant, frame: Option<u64>) {
        if pressed {
            if self.held.insert(code) {
                self.taps.insert(code, Tap { until:now + std::time::Duration::from_millis(50),
                    limit:now + std::time::Duration::from_millis(500), frame });
            }
        }
        else {
            self.held.remove(&code);
            // Release physical holds immediately once they have spanned frames.
            if self.taps.get(&code).is_some_and(|tap| !tap.visible(now, frame)) { self.taps.remove(&code); }
        }
    }
    fn sample(&mut self, now: std::time::Instant, frame: Option<u64>) -> HashSet<KeyCode> {
        self.taps.retain(|_, tap| tap.visible(now, frame));
        let mut result = self.held.clone(); result.extend(self.taps.keys().copied()); result
    }
    fn clear(&mut self) { self.held.clear(); self.taps.clear(); }
}
static KEYS: Mutex<Option<Keys>> = Mutex::new(None);''')
    replace_once(path, 'pub fn key(code: KeyCode, pressed: bool) {', '''fn presented_frame() -> Option<u64> {
    let frame = crate::display::FRAMES.load(std::sync::atomic::Ordering::Relaxed);
    (frame != 0).then_some(frame)
}
pub fn key(code: KeyCode, pressed: bool) {''')
    replace_once(path, '''    let keys = keys.get_or_insert_with(HashSet::new);
    if pressed {
        keys.insert(code);
    } else {
        keys.remove(&code);
    }''', '''    keys.get_or_insert_with(Keys::default).set(code, pressed, std::time::Instant::now(), presented_frame());''')
    replace_once(path, '''    let keys = KEYS.lock().unwrap();
    let (mut buttons, mut l, mut r) = (0, (0, 0), (0, 0));
    for c in keys.iter().flatten().filter_map(|&k| control(k)) {''', '''    let keys = KEYS.lock().unwrap().get_or_insert_with(Keys::default).sample(std::time::Instant::now(), presented_frame());
    let (mut buttons, mut l, mut r) = (0, (0, 0), (0, 0));
    for c in keys.iter().filter_map(|&k| control(k)) {''')
    replace_once(path, '    s.buttons |= stick_bits(s.left, button::STICK_L_LEFT) | stick_bits(s.right, button::STICK_R_LEFT);', '''    s.buttons |= stick_bits(s.left, button::STICK_L_LEFT) | stick_bits(s.right, button::STICK_R_LEFT);
    if crate::env_var!("KIRIKAE_INPUT_TRACE").is_some() {
        use std::sync::atomic::{AtomicU64, Ordering::Relaxed};
        static LAST: AtomicU64 = AtomicU64::new(0);
        if LAST.swap(s.buttons, Relaxed) != s.buttons { eprintln!("kirikae: sampled buttons {:#x}", s.buttons); }
    }''')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('''
#[cfg(test)]
mod decomp_key_tests {
    use super::*;
    #[test]
    fn short_taps_span_a_thirty_hz_frame_and_then_expire() {
        let mut keys = Keys::default();
        let now = std::time::Instant::now(); let ms = std::time::Duration::from_millis;
        keys.set(KeyCode::KeyZ, true, now, None); keys.set(KeyCode::KeyZ, false, now, None);
        assert!(keys.sample(now, None).contains(&KeyCode::KeyZ));
        assert!(keys.sample(now + ms(34), None).contains(&KeyCode::KeyZ));
        assert!(keys.sample(now + ms(50), None).is_empty());
    }
    #[test]
    fn a_short_tap_survives_slow_frames_but_expires_if_rendering_stalls() {
        let mut keys = Keys::default(); let now = std::time::Instant::now();
        let ms = std::time::Duration::from_millis;
        keys.set(KeyCode::KeyH, true, now, Some(100)); keys.set(KeyCode::KeyH, false, now, Some(100));
        assert!(keys.sample(now + ms(90), Some(100)).contains(&KeyCode::KeyH));
        assert!(keys.sample(now + ms(180), Some(101)).contains(&KeyCode::KeyH));
        assert!(keys.sample(now + ms(200), Some(102)).is_empty());
        keys.set(KeyCode::KeyH, true, now, Some(100)); keys.set(KeyCode::KeyH, false, now, Some(100));
        assert!(keys.sample(now + ms(500), Some(100)).is_empty());
        keys.set(KeyCode::KeyH, true, now, Some(100)); keys.set(KeyCode::KeyH, false, now + ms(60), Some(100));
        assert!(keys.sample(now + ms(90), Some(100)).contains(&KeyCode::KeyH));
        assert!(keys.sample(now + ms(200), Some(102)).is_empty());
    }
    #[test]
    fn held_keys_remain_down_and_focus_loss_clears_pending_edges() {
        let mut keys = Keys::default(); let now = std::time::Instant::now();
        let later = now + std::time::Duration::from_secs(1);
        keys.set(KeyCode::KeyZ, true, now, Some(100)); assert!(keys.sample(later, Some(100)).contains(&KeyCode::KeyZ));
        keys.set(KeyCode::KeyZ, false, later, Some(100)); assert!(keys.sample(later, Some(100)).is_empty());
        keys.set(KeyCode::KeyX, true, later, Some(100)); keys.clear(); assert!(keys.sample(later, Some(100)).is_empty());
    }
}
''')
