# Editable Switch native project

Guest AArch64 instructions are translated ahead of time into `game/*.c`.
The host services, threads, Maxwell shader translator, Vulkan renderer, audio,
controllers and save filesystem are source-shipped in `sdk/`. The normal build
has no guest CPU interpreter and does not compile guest instructions at runtime.
Untranslated targets, changed code, missing services and unsupported shader
instructions stop execution and appear in the JSON run report.

Build with Rust 1.95+, Clang 18+, CMake 3.20+ and a C++20 compiler. On Linux install
ALSA and udev development packages (`libasound2-dev libudev-dev` on Debian).
Cargo downloads the exact dependencies pinned in `sdk/Cargo.lock` on first build.
A Vulkan 1.3 driver is required for graphics.

```
cmake -S . -B build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
./build/switch_native --assets assets --report run-report.json
```

The window opens at the active monitor size. F11 toggles borderless fullscreen;
resizing updates the drawable. Keyboard: WASD/arrows left stick, IJKL right stick, Z/X/C/V face buttons,
E/U shoulders, Q/O triggers, Enter plus and Backspace minus.
Gamepads are supported. Saves are isolated by title identity under the host data
folder; `--saves PATH` chooses another save root. Keep this folder across rebuilds.

`--renderer auto|vulkan|software` selects the renderer. Software selects a Vulkan
CPU device such as Mesa llvmpipe, and is explicitly recorded in the report.
`--headless` suppresses the desktop window; `--frames N` bounds a development run.
GPU shaders are translated to SPIR-V at runtime; this does not execute guest CPU
instructions. The run report records actual device, frames, native calls and
coverage failures. A zero-frame CPU test does not qualify graphics or a game.

Inputs must be your extracted, decrypted ExeFS or a homebrew NRO/NSO. Optional
`--romfs FILE` during export includes an extracted RomFS image. Exported assets
are private and checked against the input snapshot on every run. The export
manifest binds all generated sources and assets; source edits intentionally
change that snapshot. Keep original inputs separately.

This is an experimental per-title development backend. Static discovery can
miss computed targets; unsupported Horizon, NVN, Maxwell and filesystem behavior
needs implementation for affected games. Original fixture qualification is not
retail gameplay or a completed game port. Never enable `diagnostic-interpreter`
when assessing native execution.
