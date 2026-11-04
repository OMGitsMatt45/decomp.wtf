use super::{errors, invalid_handle, KObject, System};

pub(super) fn get(system: &mut System) {
    let [_, handle, kind, ..] = system.cpu.regs;
    let Some(id) = system.kernel.resolve(handle) else {
        system.cpu.regs[0] = invalid_handle(system, handle, "GetHandleInfo");
        return;
    };
    let (low, high) = match kind {
        // The runtime creates the guest process at virtual tick zero.
        0 if matches!(system.kernel.objects.get(id), Some(KObject::Process)) => (0, 0),
        0 | 2 => (system.cpu.regs[5], system.cpu.regs[6]),
        1 => {
            let references = system.kernel.objects.refcount(id) as i32;
            (references as u32, (references >> 31) as u32)
        }
        0x32107 => (0, 0),
        _ => {
            system.cpu.regs[0] = errors::INVALID_ENUM_VALUE.0;
            return;
        }
    };
    system.cpu.regs[..3].copy_from_slice(&[0, low, high]);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::object::CURRENT_PROCESS;

    #[test]
    fn reports_process_creation_and_validates_handles() {
        let mut system = System::new(Default::default());
        system.cpu.cycles = 1200;
        system.cpu.regs[..3].copy_from_slice(&[0, CURRENT_PROCESS, 0]);
        super::super::dispatch(&mut system, 0x29);
        assert_eq!(system.cpu.regs[..3], [0, 0, 0]);
        assert!(system.unimplemented_svcs.is_empty());

        system.cpu.regs[..3].copy_from_slice(&[0, CURRENT_PROCESS, 1]);
        get(&mut system);
        assert_eq!(system.cpu.regs[..3], [0, 1, 0]);

        system.cpu.regs[..3].copy_from_slice(&[0, 0x1234, 0]);
        get(&mut system);
        assert_eq!(system.cpu.regs[0], errors::INVALID_HANDLE.0);
    }
}
