"""Small checked integration changes to the immutable upstream runtime copy."""
from pathlib import Path
import shutil

from ..pc import PCError


def replace(root, name, before, after):
    path = root/name
    text = path.read_text(encoding='utf-8')
    if text.count(before) != 1:
        raise PCError('pinned 3DS runtime integration no longer applies: '+name)
    path.write_text(text.replace(before, after), encoding='utf-8', newline='\n')


def apply_handle_info(root):
    kernel = Path(root) / 'runtime/crates/zakuro-core/src/kernel'
    shutil.copyfile(Path(__file__).with_name('svc_handle_info.rs'), kernel / 'svc_handle_info.rs')
    replace(kernel, 'svc.rs',
        'use crate::System;\n',
        'use crate::System;\n\n#[path = "svc_handle_info.rs"]\nmod svc_handle_info;\n')
    replace(kernel, 'svc.rs',
        '        0x28 => get_system_tick(system),',
        '        0x28 => get_system_tick(system),\n        0x29 => svc_handle_info::get(system),')


def apply_local_friend_lookup(root):
    services = Path(root) / 'runtime/crates/zakuro-core/src/services'
    replace(services, 'uds.rs', '\nfn reply_static(', '\npub(super) fn reply_static(')
    replace(services, 'frd.rs',
        '        // GetLastResponseResult, what the last request to the servers got',
        '''        // UnscrambleLocalFriendCode only returns codes from the console's
        // friend list. The offline console has no friends, so all are zero.
        0x001C => {
            let count = buffer.get(memory, 1);
            let input = buffer.get(memory, 2);
            if header.0 != 0x001C_0042 || input & 0x3FFF != 0x402
                || count.checked_mul(12) != Some(input >> 14)
            {
                buffer.reply_error(memory, command, errors::INVALID_COMBINATION.0);
            } else {
                super::uds::reply_static(system, buffer, command, &[], &[], count as usize * 8);
            }
        }
        // GetLastResponseResult, what the last request to the servers got''')


def apply(root):
    root = Path(root)
    apply_handle_info(root)
    replace(root, 'runtime/Cargo.toml',
        'recomp-abi = { git = "https://github.com/fearkov/3dsrecomp" }',
        'recomp-abi = { path = "../recompiler/abi" }')
    replace(root, 'runtime/Cargo.toml',
        'zakuro-gpu    = { path = "crates/zakuro-gpu" }',
        'zakuro-gpu    = { path = "crates/zakuro-gpu", default-features = false }')
    replace(root, 'runtime/crates/zakuro/Cargo.toml',
        'recomp3ds = { git = "https://github.com/fearkov/3dsrecomp" }',
        'recomp3ds = { path = "../../../recompiler" }')
    # Strict mode must reject both an unknown dispatch target and an instruction
    # the emitter explicitly handed back. Neither may execute the interpreter.
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '    pub find_recompiled: bool,',
        '    pub find_recompiled: bool,\n    pub strict_static: bool,')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            find_recompiled: false,',
        '            find_recompiled: false,\n            strict_static: false,')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '                self.interpreted_instructions += 1;',
        '''                if self.config.strict_static {
                    self.static_misses.insert(self.cpu.regs[15] | self.cpu.cpsr.thumb as u32);
                    return StepOutcome::Faulted;
                }
                // Record region entries during explicit compatibility runs.
                // These are discovery hints, never native qualification.
                if !self.coverage_interpreting {
                    let target=self.cpu.regs[15] | self.cpu.cpsr.thumb as u32;
                    if self.static_misses.len()<4096 || self.static_misses.contains(&target) { self.static_misses.insert(target); }
                    else { self.coverage_truncated=true; }
                }
                self.coverage_interpreting=true;
                self.interpreted_instructions += 1;''')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            Some(exit) => {\n                // its writes',
        '            Some(exit) => {\n                self.coverage_interpreting=false;\n                // its writes')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '    pub unimplemented_svcs: BTreeSet<u32>,',
        '    pub unimplemented_svcs: BTreeSet<u32>,\n    pub static_misses: BTreeSet<u32>,\n    coverage_interpreting: bool,\n    pub coverage_truncated: bool,')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            unimplemented_svcs: BTreeSet::new(),',
        '            unimplemented_svcs: BTreeSet::new(),\n            static_misses: BTreeSet::new(),\n            coverage_interpreting: false,\n            coverage_truncated: false,')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '        if !self.memory.is_executable(pc) {',
        '''        if !self.memory.is_executable(pc) {
            if self.config.strict_static {
                self.static_misses.insert(pc | self.cpu.cpsr.thumb as u32);
                return StepOutcome::Faulted;
            }''')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            Some(Exit::Undefined { pc, opcode }) => {',
        '''            Some(Exit::Undefined { pc, opcode }) => {
                if self.config.strict_static {
                    self.static_misses.insert(pc | self.cpu.cpsr.thumb as u32);
                    return StepOutcome::Faulted;
                }''')
    replace(root, 'runtime/crates/zakuro-core/src/recompiled.rs',
        '    fallbacks: Cell<u64>,',
        '    fallbacks: Cell<u64>,\n    pub forbid_fallback: bool,\n    pub rejected: Cell<Option<u32>>,\n    pub rejected_count: Cell<u64>,')
    replace(root, 'runtime/crates/zakuro-core/src/recompiled.rs',
        'Library { code, fallbacks: Cell::new(0), found: Library::nothing_found() }',
        'Library { code, fallbacks: Cell::new(0), forbid_fallback: false, rejected: Cell::new(None), rejected_count: Cell::new(0), found: Library::nothing_found() }')
    replace(root, 'runtime/crates/zakuro-core/src/recompiled.rs',
        '        machine.library.fallbacks.set(machine.library.fallbacks.get() + 1);',
        '''        if machine.library.forbid_fallback {
            machine.library.rejected.set(Some(address | (*ctx).thumb as u32));
            machine.library.rejected_count.set(machine.library.rejected_count.get() + 1);
            load(&*ctx, machine.cpu);
            machine.cpu.regs[15] = address;
            (*ctx).r[15] = address;
            machine.pending = Some(Exit::Undefined { pc: address, opcode: _opcode });
            (*ctx).exit = EXIT_UNWIND;
            return;
        }
        machine.library.fallbacks.set(machine.library.fallbacks.get() + 1);''')
    replace(root, 'runtime/crates/zakuro-core/src/services/mod.rs',
        '    buffer.reply(&mut system.memory, command, &[]);\n    for index in 2..8 {',
        '    buffer.reply_error(&mut system.memory, command, zakuro_common::result::errors::UNIMPLEMENTED.0);\n    for index in 2..8 {')
    replace(root, 'runtime/crates/zakuro-core/src/services/misc.rs',
        '        // -- Wifi connection ------------------------------------------------',
        '''        // Offline socket initialization fails without opening a host socket.
        "soc:U" if header.0 == 0x0001_0044 => {
            buffer.reply_error(&mut system.memory, command, zakuro_common::result::errors::NOT_CONNECTED.0);
            true
        }

        // -- Wifi connection ------------------------------------------------''')
    replace(root, 'runtime/crates/zakuro-core/src/services/mod.rs',
        'pub mod apt;', 'pub mod apt;\n#[path = "ac_offline.rs"] mod ac_offline;')
    replace(root, 'runtime/crates/zakuro-core/src/services/mod.rs',
        '        _ => misc::handle(system, &buffer, header, &name),',
        '''        "ac:u" | "ac:i" => ac_offline::handle(system, &buffer, header)
            || misc::handle(system, &buffer, header, &name),
        _ => misc::handle(system, &buffer, header, &name),''')
    replace(root, 'runtime/crates/zakuro-core/src/room.rs',
        '        let listener = TcpListener::bind(("0.0.0.0", port))?;',
        '''        Self::bind(std::net::SocketAddr::from(([0, 0, 0, 0], port)), name, password, most)
    }

    /// Opens a room on a caller-selected interface, including loopback.
    pub fn bind(address: std::net::SocketAddr, name: &str, password: &str, most: usize) -> std::io::Result<Server> {
        let listener = TcpListener::bind(address)?;''')
    replace(root, 'runtime/crates/zakuro-core/src/services/uds.rs',
        '''    // with no room wireless is off, the way the offline answer has it,
    // unless a title already started on it in one
    if !system.services.uds.initialized && system.room.as_ref().is_none_or(|room| !room.open()) {
        return false;
    }
    let command = header.command_id();''',
        '''    let command = header.command_id();
    // Local UDS resources can be created before joining a host room.
    // Hosting and joining still require an open room.
    if !matches!(command, 0x0001 | 0x001B)
        && !system.services.uds.initialized
        && system.room.as_ref().is_none_or(|room| !room.open())
    {
        return false;
    }''')
    replace(root, 'runtime/crates/zakuro-core/src/services/uds.rs',
        '    /// one console hosts a network, the other finds it scanning, reads its',
        '''    #[test]
    fn initialize_without_a_room_reports_disconnected() {
        let (mut system, buffer) = system_with_thread();
        initialize(&mut system, &buffer, 'A');
        let event = buffer.get(&mut system.memory, 3);
        assert!(system.kernel.resolve(event).is_some());
        assert_eq!(request(&mut system, &buffer, &[0x000B_0000]), 0);
        assert_eq!(buffer.get(&mut system.memory, 2), NOT_CONNECTED);
        assert_eq!(request(&mut system, &buffer, &[0x001A_0000]), 0);
        assert_eq!(buffer.get(&mut system.memory, 2), 0);
    }

    /// one console hosts a network, the other finds it scanning, reads its''')
    import shutil
    apply_local_friend_lookup(root)
    shutil.copyfile(Path(__file__).with_name('ac_offline.rs'),root/'runtime/crates/zakuro-core/src/services/ac_offline.rs')
    shutil.copyfile(Path(__file__).with_name('cecd_empty.rs'),root/'runtime/crates/zakuro-core/src/services/cecd_empty.rs')
    replace(root,'runtime/crates/zakuro-core/src/services/cecd.rs',
        'use crate::System;',
        'use crate::System;\n#[path="cecd_empty.rs"] mod empty;')
    replace(root,'runtime/crates/zakuro-core/src/services/cecd.rs',
        '    let command = header.command_id();',
        '    if empty::handle(system,buffer,header) { return true; }\n    let command = header.command_id();')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            let mut limit = deadline.unwrap_or(self.cpu.cycles + CYCLES_PER_FRAME);',
        '            // A blocked client still needs the next LCD interrupt before the outer budget.\n'
        '            let mut limit = deadline.unwrap_or(self.cpu.cycles + CYCLES_PER_FRAME)\n'
        '                .min(self.next_frame_boundary);')
    apply_gsp_lifetime(root)
    apply_graphics(root)
    apply_microphone(root)
    apply_cro_cheat_aliases(root)


def apply_cro_cheat_aliases(root):
    """Resolve cheat addresses through the 3DS loader's copied code ranges."""
    import shutil

    core = Path(root) / 'runtime/crates/zakuro-core/src'
    shutil.copyfile(Path(__file__).with_name('cheat_cro.rs'), core/'cheat_cro.rs')
    replace(core, 'cheats.rs', 'struct CodeRanges {',
        'struct CodeRanges {\n    aliases: Vec<cro_alias::CodeAlias>,')
    replace(core, 'cheats.rs', 'impl CodeRanges {\n    fn of(system: &System)',
        '#[path = "cheat_cro.rs"]\nmod cro_alias;\n\nimpl CodeRanges {\n    fn of(system: &mut System)')
    replace(core, 'cheats.rs', 'CodeRanges { text, modules, text_changed:',
        'CodeRanges { aliases: cro_alias::code_aliases(system), text, modules, text_changed:')
    replace(core, 'cheats.rs', '            write(system, ranges, addr, 1, original as u32);',
        '            write_at(system, ranges, addr, 1, original as u32);')
    replace(core, 'cheats.rs', 'fn write(system: &mut System, ranges: &mut CodeRanges, addr: u32, size: u32, value: u32) {',
        '''fn read_cheat(system: &mut System, ranges: &CodeRanges, addr: u32, size: u32) -> u32 {
    read(system, cro_alias::resolve(&ranges.aliases, addr, size), size)
}

fn write(system: &mut System, ranges: &mut CodeRanges, addr: u32, size: u32, value: u32) {
    let target = cro_alias::resolve(&ranges.aliases, addr, size);
    write_at(system, ranges, target, size, value);
}

fn write_at(system: &mut System, ranges: &mut CodeRanges, addr: u32, size: u32, value: u32) {''')
    for expression in (
        'holds(line.value, read(system, addr, 4))',
        'read(system, addr, 2)',
        's.offset = read(system, addr, 4)',
        'read(system, line.value.wrapping_add(s.offset), size)',
    ):
        replace(core, 'cheats.rs', expression, expression.replace('read(system, ', 'read_cheat(system, ranges, '))


def apply_microphone(root):
    """Install the guest MIC service with a silent host source."""
    import shutil

    core = Path(root) / 'runtime/crates/zakuro-core/src'
    shutil.copyfile(Path(__file__).with_name('mic_silent.rs'), core/'services/mic_silent.rs')
    replace(core, 'services/mod.rs', 'pub mod misc;', 'pub mod misc;\npub mod mic_silent;')
    replace(core, 'services/mod.rs', '    pub cam: cam::CamState,',
        '    pub cam: cam::CamState,\n    #[serde(skip)]\n    pub mic: mic_silent::MicState,')
    replace(core, 'services/mod.rs', '        "cam:u" | "cam:s" => cam::handle(system, &buffer, header),',
        '        "cam:u" | "cam:s" => cam::handle(system, &buffer, header),\n'
        '        "mic:u" => mic_silent::handle(system, &buffer, header),')
    replace(core, 'lib.rs', '        services::cam::tick(self);',
        '        services::cam::tick(self);\n        services::mic_silent::tick(self);')
    # Keep the original postcard layout so pre-MIC savestates still load.
    replace(core, 'state/mod.rs', '        Ok(out)',
        '''        let mic = postcard::to_allocvec(&self.services.mic)
            .map_err(|error| format!("the microphone state could not be written, {error}"))?;
        section(&mut out, &mic);
        Ok(out)''')
    replace(core, 'state/mod.rs',
        '        let memories = [reader.section()?, reader.section()?, reader.section()?, reader.section()?];',
        '''        let memories = [reader.section()?, reader.section()?, reader.section()?, reader.section()?];
        let mic = if reader.0.is_empty() {
            crate::services::mic_silent::MicState::default()
        } else {
            postcard::from_bytes(&reader.section()?)
                .map_err(|error| format!("the microphone state could not be read, {error}"))?
        };''')
    replace(core, 'state/mod.rs', '        self.services = saved.services;',
        '        self.services = saved.services;\n        self.services.mic = mic;')


def apply_graphics(root):
    root = Path(root)
    replace(root,'runtime/crates/zakuro-gpu/src/lib.rs',
        '    /// whether the 3D is drawn on the host\'s GPU, enable_hardware_renderer\n',
        '''    /// The actual Vulkan driver's undecorated device identity.
    pub fn hardware_device_name(&self) -> Option<&str> {
        #[cfg(feature="vulkan")]
        { self.resources.hardware.as_ref().map(|hardware|hardware.name()) }
        #[cfg(not(feature="vulkan"))]
        { None }
    }

    /// whether the 3D is drawn on the host's GPU, enable_hardware_renderer
''')
    replace(root, 'runtime/crates/zakuro-gpu/src/raster/hardware.rs',
        '''    pub fn set_scale(&mut self, scale: u32) -> u32 {
        if self.surfaces.is_empty() && self.blits {
            // up to 8, and no more than keeps the largest buffers, 1024
            // pixels across, within what the GPU makes
            self.scale = scale.clamp(1, 8).min((self.max_image_size / 1024).max(1));
        }
        self.scale
    }''',
        '''    pub fn supported_scale(&self, scale: u32) -> u32 {
        if self.blits { scale.clamp(1, (self.max_image_size / 1024).max(1)) } else { 1 }
    }

    pub fn set_scale(&mut self, scale: u32) -> u32 {
        if self.surfaces.is_empty() {
            self.scale = self.supported_scale(scale);
        }
        self.scale
    }''')
    replace(root, 'runtime/crates/zakuro-gpu/src/lib.rs',
        '    /// how many times the console\'s resolution the host\'s GPU draws at, 1\n',
        '''    /// Change render resolution after flushing all GPU-owned guest data.
    /// Keep the old renderer when allocating the replacement fails.
    #[cfg(feature = "vulkan")]
    pub fn retarget_scale<M: GpuMemory>(&mut self, memory: &mut M, scale: u32,
        device: Option<std::sync::Arc<SharedDevice>>, title: Option<u64>) -> Result<u32, String> {
        let old = self.resources.hardware.as_mut().ok_or("no Vulkan geometry renderer")?;
        let scale = old.supported_scale(scale);
        if old.scale() == scale { return Ok(scale); }
        old.flush(memory)?;
        if let Some(shared) = device.as_ref() {
            // A presenter sharing this device may still sample the old images.
            // Both submit on this thread; finish those reads before replacing
            // the renderer and destroying its image views.
            unsafe { shared.device.device_wait_idle() }
                .map_err(|error|format!("waiting for shared Vulkan device: {error:?}"))?;
        }
        self.enable_hardware_renderer(scale, device, title)?;
        Ok(self.scale())
    }

    /// how many times the console's resolution the host's GPU draws at, 1
''')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '    pub fn set_interpolation(&mut self, on: bool) -> bool {',
        '''    pub fn resize_drawable(&mut self, width: u32, height: u32,
        layout: zakuro_gpu::ScreenLayout) -> Result<u32, String> {
        if width == 0 || height == 0 { return Ok(self.gpu.scale()); }
        let (top, bottom) = zakuro_gpu::backend::layout(width, height, layout, 400.0, false);
        // Supersample to cover the actual drawable in either arrangement.
        // Only the device's image limit caps the requested render resolution.
        let wanted = top.map_or(1, |v| (v.width / 400.0).ceil() as u32)
            .max(bottom.map_or(1, |v| (v.width / 320.0).ceil() as u32)).max(1);
        self.set_render_scale(wanted)
    }

    pub fn set_render_scale(&mut self, wanted: u32) -> Result<u32, String> {
        if wanted == self.gpu.scale() { return Ok(wanted); }
        let mut memory = GuestMemory { memory: &mut self.memory, linear_base: self.kernel.linear_base };
        let scale = self.gpu.retarget_scale(&mut memory, wanted,
            self.config.device.clone(), self.title.as_ref().map(|title| title.program_id()))?;
        self.config.resolution = scale;
        self.showing = [None; 3];
        self.pacing = Pacing::default();
        Ok(scale)
    }

    pub fn set_interpolation(&mut self, on: bool) -> bool {''')


def apply_gsp_lifetime(root):
    """GSP owns its shared block; closing a client handle must not destroy it."""
    root = Path(root)
    replace(root, 'runtime/crates/zakuro-core/src/services/gsp.rs',
        '    pub shared_memory_handle: Option<u32>,',
        '    pub shared_memory_handle: Option<u32>,\n'
        '    pub shared_memory_object: Option<crate::kernel::object::ObjectId>,')
    replace(root, 'runtime/crates/zakuro-core/src/services/gsp.rs',
        '''    if let Some(handle) = system.services.gsp.shared_memory_handle {
        return handle;
    }''',
        '''    if let Some(object) = system.services.gsp.shared_memory_object {
        if let Some(handle) = system.services.gsp.shared_memory_handle {
            if system.kernel.resolve(handle) == Some(object) { return handle; }
        }
        // A service reconnection receives a live handle to the same block.
        let handle = system.kernel.handles.create(&mut system.kernel.objects, object, "GSP shared memory");
        system.services.gsp.shared_memory_handle = Some(handle);
        return handle;
    }''')
    replace(root, 'runtime/crates/zakuro-core/src/services/gsp.rs',
        '''    let handle = system
        .kernel
        .handles
        .create(&mut system.kernel.objects, object, "GSP shared memory");''',
        '''    system.kernel.objects.add_ref(object);
    system.services.gsp.shared_memory_object = Some(object);
    let handle = system
        .kernel
        .handles
        .create(&mut system.kernel.objects, object, "GSP shared memory");''')
