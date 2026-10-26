# 3DS native runtime development project

`game/` contains editable ARM/Thumb/VFP C translated from the identified input.
`native/runtime/` contains the pinned MIT 3DS kernel, service, filesystem, CRO,
audio and PICA200 source. `native/recompiler/` supplies its matching ABI. There
is no dependency on an installed emulator or decomp.wtf after export.

RomFS CRO/CRS payloads are retained under `assets/modules/` with numeric filenames
and logical paths/hashes in `analysis.json`. Module exports/imports/relocations
feed C generation; the bundled loader places their generated functions when a
module is loaded. Original module checks cover ARM/Thumb relocation, changed-code
guards, reload and unload. Retail module/service coverage remains unqualified.

This is a runtime development project with a Vulkan window and bounded headless
runner. Audio and controller input are connected; retail gameplay and physical
device acceptance remain unqualified. It does not open a game-library browser.

Install Rust 1.95+, CMake and a host C/C++ compiler. On Windows, use MSVC Rust
with Visual Studio C++ tools. Build from this directory:

```
cmake -S . -B build
cmake --build build --target ctr_runtime --config Release
build/host/debug/ctr_runtime PATH_TO_ORIGINAL_IMAGE --cycles 1000000 --data user
```

On Windows the executable is `build/host/debug/ctr_runtime.exe`.
For an optimized host build, configure `-DCTR_CARGO_PROFILE=release` and run
`build/host/release/ctr_runtime`. The C library and Rust runtime link into one
executable. Changes to generated C are rebuilt and relinked by the same command.

Linux desktop builds also need pkg-config, ALSA and libudev development packages
and X11 libraries (`pkg-config libasound2-dev libudev-dev` on Ubuntu/Debian).
Windows uses CPAL/Gilrs with the system audio/controller APIs and MSVC Rust.

For the adaptive window, run:

```
build/host/debug/ctr_runtime PATH_TO_ORIGINAL_IMAGE --window --screens unified
```

`--screens stacked` preserves the console arrangement. Unified composition fits
one primary picture to the current drawable and keeps the other as an inset;
`--primary bottom` swaps them. F6 changes layout, F7 swaps the primary, F11 toggles
fullscreen on the window's monitor and Escape closes the window. All rectangles,
touch coordinates and geometry render resolution follow resize and high DPI.
The screens keep their native aspect ratios. This composition does not infer a
continuous camera from two independent game pictures or expand a game's field of
view; that remains additional scene-level work. Neither picture is discarded.

J/K/U/I are A/B/X/Y, Q/E are L/R, arrows are the D-pad, WASD is the circle pad,
and Enter/Backspace are Start/Select. Click the lower-screen picture for touch.
The top inset never passes clicks through to a primary lower screen.
DSP samples go to the selected host's default audio output, with resampling and
a bounded queue. `--mute` disables it. Standard gamepads merge with keyboard and
touch; left/right sticks drive the circle pad/C-stick. Reports say whether audio
opened, how many frames were queued, how many controllers were seen and why a
device failed. These observations do not claim physical device qualification.
Use `--window-frames N` for bounded window checks.
Without `--cycles`, a window runs until closed; the headless runner defaults to
one million guest cycles. `--gpu` enables Vulkan geometry in the headless runner.

`ctr_gpu_scenes` checks original PICA triangle commands at changing render scales,
compares independent software PICA results and verifies GPU-owned framebuffer
data survives resize. `ctr_gpu_scenes --layout-only` checks adaptive rectangles,
touch mapping and draw order without needing Vulkan. Software Vulkan can pass
these checks; physical hardware qualification is separate.

`cmake --build build --target ctr_runtime_tests --config Release` runs the original
audio queue/resampling and controller merge checks. An optional virtual audio
device can also verify that the actual callback consumes a nonzero original tone.
This is signal-path evidence, not retail DSP or physical-speaker acceptance.

The original input must match its exact SHA-256 before execution. Neither a
BIOS nor system firmware is required by the HLE kernel. Some titles may need
additional owner-supplied system files; unsupported services are reported.

Execution defaults to strict static mode. Missing translated targets and
unsupported instructions stop before running the interpreter. The generated
code can resume at every instruction, including a scheduler budget boundary.
`--allow-interpreter` explicitly permits compatibility fallback. The JSON report
counts direct and inline interpreted instructions separately from native work
and records rejected instructions, missing PCs and unsupported services.
Exit 0 means ExitProcess, 1 means a fault/unsupported operation, and 2 means the
cycle budget expired. A successful bounded run does not establish a playable port.

Runtime dependencies are locked in `native/app/Cargo.lock`. No game-specific
source overrides or automatic downloads of firmware, keys or game data are used.
Save files are kept under the selected `--data` directory. Keep owner-derived
source, original assets and save data private.
