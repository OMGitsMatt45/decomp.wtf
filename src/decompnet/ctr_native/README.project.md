# 3DS native CPU development project

This is an independent C/C++ source project generated from your decrypted
executable. `game/` contains editable translated ARM/Thumb/VFP C. `runtime/`
contains a bounded CPU harness; `assets/` contains the executable's original
segments. Rust and decomp.wtf are not needed to build this output.

```
cmake -S . -B build
cmake --build build --config Release
./build/ctr_probe ./assets 100000
```

On Visual Studio, run `build/Release/ctr_probe.exe assets 100000`.

ExitProcess is the only implemented kernel service. Unknown instructions,
untranslated targets, unsupported services, memory permission violations and
asset changes fail explicitly. There is no interpreter or JIT fallback.
An instruction budget bounds execution; hitting it returns status 2.

This milestone does not provide a playable 3DS port. The kernel/service runtime,
CRO modules, RomFS access, PICA200 GPU, adaptive dual-screen presentation, audio,
input and saves still need integration and qualification. The completed game
export will follow the same source-project and adaptive GPU contract as DS,
PS1, PS2 and GBA. Keep owner-derived game source and assets private.
