"""Pass real applet storage to a desktop software-keyboard dialog."""
from pathlib import Path
from .patches import replace_once


def apply(root, adapter):
    rt = Path(root) / 'crates/rt'
    services = rt / 'src/services/mod.rs'
    replace_once(services, '#[derive(Clone, Debug, Default)]\npub struct Request {', '''#[derive(Clone)]
pub struct InputObject(pub Arc<dyn Service>);
impl std::fmt::Debug for InputObject {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str(&self.0.name()) }
}
#[derive(Clone, Debug, Default)]
pub struct Request {''')
    replace_once(services, '    pub objects: Vec<u32>,', '    pub objects: Vec<u32>,\n    pub input_objects: Vec<InputObject>,')
    replace_once(services, '    fn name(&self) -> String;\n    fn call(',
                 '    fn name(&self) -> String;\n    fn storage_bytes(&self, _memory: &crate::mem::GuestMemory, _limit: usize) -> Option<Vec<u8>> { None }\n    fn call(')
    ipc = rt / 'src/ipc.rs'
    replace_once(ipc, '        objects,\n    }', '        objects,\n        input_objects: Vec::new(),\n    }')
    replace_once(ipc, '    let mut reply = object.call(c, req);', '''    let mut resolved;
    let req = if !req.objects.is_empty() || !req.copy_handles.is_empty() || !req.move_handles.is_empty() {
        resolved = req.clone();
        if let Some(session) = domain {
            for &id in &req.objects {
                let Some(value) = session.domain_object(id) else { return (Reply::err(RESULT_BAD_MESSAGE), Vec::new()); };
                resolved.input_objects.push(crate::services::InputObject(value));
            }
        } else {
            for &h in req.copy_handles.iter().chain(&req.move_handles) {
                let value = p.handles.lock().unwrap().session(h).and_then(|s| s.object());
                if let Some(value) = value { resolved.input_objects.push(crate::services::InputObject(value)); }
            }
        }
        &resolved
    } else { req };
    let mut reply = object.call(c, req);''')
    storage = rt / 'src/services/am/storage.rs'
    replace_once(storage, 'impl Service for Storage {', '''impl Service for Storage {
    fn storage_bytes(&self, memory: &GuestMemory, limit: usize) -> Option<Vec<u8>> {
        match &self.backing {
            Backing::Bytes { bytes: Bytes::Owned(data), .. } => {
                let data = data.lock().unwrap();
                (data.len() <= limit).then(|| data.clone())
            }
            Backing::Bytes { bytes: Bytes::Mapped { addr, size }, .. } if *size <= limit as u64 => memory.read(*addr, *size),
            _ => None,
        }
    }''')
    am = rt / 'src/services/am'
    replace_once(am / 'mod.rs', 'mod library;', 'mod library;\nmod decomp_keyboard;')
    (am / 'decomp_keyboard.rs').write_bytes((Path(adapter) / 'software_keyboard.rs').read_bytes())
    library = am / 'library.rs'
    replace_once(library, 'const KEYBOARD_TEXT: &str = "Kirikae";', '#[cfg(test)]\nconst KEYBOARD_TEXT: &str = "Kirikae";')
    replace_once(library, '    output: Mutex<Option<Vec<u8>>>,', '    output: Mutex<Option<Vec<u8>>>,\n    inputs: Mutex<Vec<Vec<u8>>>,')
    replace_once(library, '            output: Mutex::new(None),', '            output: Mutex::new(None),\n            inputs: Mutex::new(Vec::new()),')
    replace_once(library, '''                let mut out = vec![0u8; KEYBOARD_OUTPUT_SIZE];
                for (i, unit) in KEYBOARD_TEXT.encode_utf16().enumerate() {
                    out[4 + i * 2..6 + i * 2].copy_from_slice(&unit.to_le_bytes());
                }
                Some(out)''', '''                Some(super::decomp_keyboard::output(&self.inputs.lock().unwrap(), KEYBOARD_OUTPUT_SIZE))''')
    replace_once(library, '    fn push_storage(&self, req: &Request) -> Reply {\n        if req.objects.is_empty() {', '''    fn push_storage(&self, c: &Cpu, req: &Request) -> Reply {
        if self.id == APPLET_SOFTWARE_KEYBOARD && req.cmd == 100 && !req.input_objects.is_empty() {
            let Some(bytes) = req.input_objects[0].0.storage_bytes(&c.process().memory, 2 * 1024 * 1024) else {
                return Reply::err(RESULT_INVALID_PARAMETERS);
            };
            let mut inputs = self.inputs.lock().unwrap();
            if inputs.len() >= 4 { return Reply::err(RESULT_INVALID_PARAMETERS); }
            inputs.push(bytes);
        }
        if req.objects.is_empty() && req.input_objects.is_empty() {''')
    replace_once(library, '100 | 102 | 103 => self.push_storage(req),', '100 | 102 | 103 => self.push_storage(c, req),')
    with ipc.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('''
#[cfg(test)]
mod decomp_input_object_tests {
    use super::*;
    use crate::{abi::Entry, services::{harness, am::Storage}};
    struct Reader;
    impl Service for Reader {
        fn name(&self) -> String { "original/input-reader".into() }
        fn call(&self, c: &mut Cpu, req: &Request) -> Reply {
            assert_eq!(req.input_objects.len(), 1);
            Reply::ok().bytes(&req.input_objects[0].0.storage_bytes(&c.process().memory, 16).unwrap())
        }
    }
    #[test]
    fn input_storage_resolves_in_domains_and_handle_sessions() {
        extern "C" fn probe(c: &mut Cpu) {
            let reader: Arc<dyn Service> = Arc::new(Reader);
            let storage: Arc<dyn Service> = Arc::new(Storage::new(b"config".to_vec()));
            let domain = Session::new(reader.clone()); domain.convert_to_domain();
            let id = domain.domain_add(storage.clone());
            let (reply, _) = call(c, &reader, &Request { objects:vec![id], ..Default::default() }, Some(&domain));
            assert_eq!(reply.data, b"config");
            let (invalid, _) = call(c, &reader, &Request { objects:vec![999], ..Default::default() }, Some(&domain));
            assert_eq!(invalid.result, RESULT_BAD_MESSAGE);
            let handle = c.process().handles.lock().unwrap().insert(KObject::Session(Session::new(storage)));
            let (reply, _) = call(c, &reader, &Request { copy_handles:vec![handle], ..Default::default() }, None);
            assert_eq!(reply.data, b"config");
            c.halt();
        }
        harness::run(vec![Entry { addr:harness::ENTRY, func:probe }]);
    }
}
''')
