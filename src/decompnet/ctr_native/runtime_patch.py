"""Small checked integration changes to the immutable upstream runtime copy."""
from pathlib import Path

from ..pc import PCError


def replace(root, name, before, after):
    path = root/name
    text = path.read_text(encoding='utf-8')
    if text.count(before) != 1:
        raise PCError('pinned 3DS runtime integration no longer applies: '+name)
    path.write_text(text.replace(before, after), encoding='utf-8', newline='\n')


def apply(root):
    root = Path(root)
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
                self.interpreted_instructions += 1;''')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '    pub unimplemented_svcs: BTreeSet<u32>,',
        '    pub unimplemented_svcs: BTreeSet<u32>,\n    pub static_misses: BTreeSet<u32>,')
    replace(root, 'runtime/crates/zakuro-core/src/lib.rs',
        '            unimplemented_svcs: BTreeSet::new(),',
        '            unimplemented_svcs: BTreeSet::new(),\n            static_misses: BTreeSet::new(),')
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
    apply_graphics(root)


def apply_graphics(root):
    root = Path(root)
    import shutil
    shutil.copyfile(Path(__file__).with_name('unified.rs'),
                    root/'runtime/crates/zakuro-gpu/src/backend/unified.rs')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '//! presentation backends.\n', '//! presentation backends.\npub mod unified;\n')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '    LargeTop,\n}',
        '    LargeTop,\n    /// One adaptive canvas with the other screen as a touch-accessible inset.\n    Unified,\n    UnifiedBottom,\n}')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '            ScreenLayout::TopOnly => (top_width, 240.0),',
        '            ScreenLayout::TopOnly | ScreenLayout::Unified => (top_width, 240.0),\n'
        '            ScreenLayout::UnifiedBottom => (320.0, 240.0),')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '    let (total_width, total_height) = arrangement.size_f(top_w);',
        '''    if matches!(arrangement, ScreenLayout::Unified | ScreenLayout::UnifiedBottom) {
        return unified::places(window_width, window_height, arrangement == ScreenLayout::UnifiedBottom);
    }
    let (total_width, total_height) = arrangement.size_f(top_w);''')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '        ScreenLayout::TopOnly => None,',
        '        ScreenLayout::TopOnly | ScreenLayout::Unified | ScreenLayout::UnifiedBottom => None,')
    replace(root, 'runtime/crates/zakuro-gpu/src/backend/mod.rs',
        '        top.map(|viewport| (viewport, eye)).into_iter().chain(bottom.map(|viewport| (viewport, Shown::Bottom)))',
        '''        let mut placed = top.map(|viewport| (viewport, eye)).into_iter()
            .chain(bottom.map(|viewport| (viewport, Shown::Bottom))).collect::<Vec<_>>();
        if arrangement == ScreenLayout::UnifiedBottom { placed.reverse(); }
        placed.into_iter()''')
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
        let mut memory = GuestMemory { memory: &mut self.memory, linear_base: self.kernel.linear_base };
        let scale = self.gpu.retarget_scale(&mut memory, wanted,
            self.config.device.clone(), self.title.as_ref().map(|title| title.program_id()))?;
        self.config.resolution = scale;
        self.showing = [None; 3];
        self.pacing = Pacing::default();
        Ok(scale)
    }

    pub fn set_interpolation(&mut self, on: bool) -> bool {''')
