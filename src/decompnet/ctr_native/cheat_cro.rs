use std::ops::Range;

use zakuro_cpu::Bus;

use crate::{cro::format::header, System};

pub(super) struct CodeAlias {
    buffer: Range<u32>,
    live: u32,
}

pub(super) fn code_aliases(system: &mut System) -> Vec<CodeAlias> {
    let memory = &mut system.memory;
    system.cro.modules.iter().filter_map(|module| {
        let copy = system.cro.copies.get(&module.base)?;
        let live = memory.read32(module.base + header::CODE_OFFSET);
        let size = memory.read32(module.base + header::CODE_SIZE);
        let offset = live.checked_sub(module.base)?;
        let end = offset.checked_add(size)?;
        if size == 0 || end > copy.fixed.min(copy.block.size) {
            return None;
        }
        // ldr:ro copies the rebased header back after loading. The buffer
        // belongs to this module only as long as that header still matches.
        let buffer_header = copy.buffer.checked_add(header::CODE_OFFSET)?;
        if !memory.is_readable(buffer_header, 8)
            || memory.read32(buffer_header) != live
            || memory.read32(buffer_header + 4) != size
        {
            return None;
        }
        Some(CodeAlias {
            buffer: copy.buffer.checked_add(offset)?..copy.buffer.checked_add(end)?,
            live,
        })
    }).collect()
}

pub(super) fn resolve(aliases: &[CodeAlias], address: u32, size: u32) -> u32 {
    let Some(end) = address.checked_add(size) else { return address };
    let mut matches = aliases.iter().filter(|alias| {
        alias.buffer.contains(&address) && end <= alias.buffer.end
    });
    match (matches.next(), matches.next()) {
        (Some(alias), None) => alias.live + (address - alias.buffer.start),
        _ => address,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cro::{Copy, Module};
    use crate::memory::{MemoryRegion, MemoryState, Permission};

    #[test]
    fn cheat_conditions_and_writes_follow_the_current_copied_code() {
        const BUFFER: u32 = 0x0800_0000;
        const LIVE: u32 = 0x0070_0000;
        const OFFSET: u32 = 0x200;
        const CODE_SIZE: u32 = 0x100;
        const ORIGINAL: u32 = 0xE3A0_0001;
        const PATCHED: u32 = 0xE3A0_0002;
        let (mut system, _) = crate::services::tests::system_with_thread();
        let buffer = system.memory.phys.allocate(MemoryRegion::Application, 0x1000).unwrap();
        let live = system.memory.phys.allocate(MemoryRegion::System, 0x1000).unwrap();
        system.memory.map(BUFFER, buffer.addr, buffer.size, Permission::RW, MemoryState::Private);
        system.memory.map(LIVE, live.addr, live.size, Permission::RW | Permission::EXECUTE, MemoryState::Code);
        for base in [BUFFER, LIVE] {
            system.memory.write32(base + header::CODE_OFFSET, LIVE + OFFSET);
            system.memory.write32(base + header::CODE_SIZE, CODE_SIZE);
        }
        system.memory.write32(LIVE + OFFSET, ORIGINAL);
        system.memory.write32(BUFFER + OFFSET, 0xDEAD_BEEF);
        system.cro.copies.insert(LIVE, Copy { buffer: BUFFER, block: live, fixed: 0x1000 });
        system.cro.modules.push(Module {
            name: "Test".into(), base: LIVE, size: 0x1000, exports: Default::default(),
            indexed_exports: Vec::new(), segments: vec![LIVE + OFFSET], auto_link: false,
        });
        let mut code = super::super::Cheat::new("copied code", vec![
            "58000200 E3A00001".into(),
            "08000200 E3A00002".into(),
            "D0000000 00000000".into(),
            "08000400 12345678".into(),
        ], Vec::new());
        code.enabled = true;
        code.builtin = true;
        system.cheats.push(code);
        super::super::run(&mut system);
        assert_eq!(system.memory.read32(LIVE + OFFSET), PATCHED);
        assert_eq!(system.memory.read32(BUFFER + OFFSET), 0xDEAD_BEEF);
        assert_eq!(system.memory.read32(BUFFER + 0x400), 0x1234_5678);
        assert_eq!(system.memory.read32(LIVE + 0x400), 0);

        system.cheats[0].enabled = false;
        super::super::run(&mut system);
        assert_eq!(system.memory.read32(LIVE + OFFSET), ORIGINAL);
        assert_eq!(system.memory.read32(BUFFER + 0x400), 0);

        system.memory.write32(BUFFER + header::CODE_OFFSET, 0);
        system.memory.write32(BUFFER + OFFSET, ORIGINAL);
        system.cheats[0].enabled = true;
        super::super::run(&mut system);
        assert_eq!(system.memory.read32(BUFFER + OFFSET), PATCHED);
        assert_eq!(system.memory.read32(LIVE + OFFSET), ORIGINAL);
    }
}
