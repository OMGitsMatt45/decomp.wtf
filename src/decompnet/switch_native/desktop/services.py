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
