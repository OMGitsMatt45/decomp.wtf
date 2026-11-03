//! Complete guest connection requests in the disconnected state.
use crate::{
    kernel::{ipc::{CommandBuffer, Descriptor, Header}, object::KObject},
    System,
};
use zakuro_common::result::errors;

const CONFIG_SIZE: u32 = 0x200;

pub fn handle(system: &mut System, buffer: &CommandBuffer, header: Header) -> bool {
    let command = header.command_id();
    match header.0 {
        // CreateDefaultConfig and SetRequestEulaVersion. An offline config
        // carries no network profile. Preserve the caller's config on update.
        0x0001_0000 | 0x002D_0082 => {
            let tls = system.kernel.current().unwrap().tls;
            let memory = &mut system.memory;
            let (out, capacity) = buffer.static_buffer(memory, tls, 0);
            let mut config = [0; CONFIG_SIZE as usize];
            if capacity < CONFIG_SIZE || !memory.is_writable(out, CONFIG_SIZE) {
                buffer.reply_error(memory, command, errors::INVALID_ADDRESS.0);
                return true;
            }
            if command == 0x002D {
                let descriptor = buffer.get(memory, 3);
                let source = buffer.get(memory, 4);
                if descriptor != Descriptor::static_buffer(CONFIG_SIZE, 0)
                    || !memory.is_readable(source, CONFIG_SIZE)
                {
                    buffer.reply_error(memory, command, errors::INVALID_ADDRESS.0);
                    return true;
                }
                memory.read_bytes(source, &mut config);
            }
            memory.write_bytes(out, &config);
            buffer.set(memory, 0, Header::new(command, 1, 2).0);
            buffer.set(memory, 1, 0);
            buffer.set(memory, 2, Descriptor::static_buffer(CONFIG_SIZE, 0));
            buffer.set(memory, 3, out);
        }
        // The request completes even offline. Wake the caller so it can read
        // the disconnected result or finish closing the connection.
        0x0004_0006 | 0x0008_0004 => {
            let event_handle = buffer.get(&mut system.memory, 4);
            let event = system.kernel.resolve(event_handle)
                .filter(|&event| matches!(system.kernel.objects.get(event), Some(KObject::Event(_))));
            if let Some(event) = event {
                system.kernel.signal_event(event);
                buffer.reply(&mut system.memory, command, &[]);
            } else {
                buffer.reply_error(&mut system.memory, command, errors::INVALID_HANDLE.0);
            }
        }
        0x0005_0002 => buffer.reply_error(&mut system.memory, command, errors::NOT_CONNECTED.0),
        0x0009_0002 => buffer.reply(&mut system.memory, command, &[]),
        // GetInfraPriority for the default profile.
        0x0027_0002 => buffer.reply(&mut system.memory, command, &[0]),
        _ => return false,
    }
    true
}
