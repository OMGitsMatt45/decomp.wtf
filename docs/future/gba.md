# GBA native PC output

Status: **experimental desktop backend; retail qualification in progress**.
The goal is the same independent editable repository as DS/PS1/PS2: translated
game code, source-shipped hardware runtime, a desktop CMake build, adaptive GPU
presentation, audio, controllers, cartridge saves and explicit compatibility reports.

## Implemented foundation

- An input-validating `pc gba-inspect` command, `pc gba-native` desktop exporter and `pc gba-probe` diagnostic exporter.
- ARMv4T ARM/Thumb discovery and native C translation through pinned MIT
  [AnyGBA](https://github.com/hoanglt1223/anygba/tree/a3eb412f79627eaae27e2523039d893f72dada1d).
- An independent C11/C++20 project containing translated code and the hardware core;
  the user's cartridge is staged privately by a SHA-256-verifying extraction script.
- Input-bound code profiles for callbacks and ROM-to-RAM code copies. Runtime byte
  checks prevent modified RAM code from executing stale native instructions.
- Headless frame/PCM capture, input, RAM observations and raw save persistence.
  The player contains no interpreter; an optional separate probe retains the
  reference implementation for validation and coverage investigation.
- Automatic callback-table discovery, native secondary entries for decoded
  instruction boundaries, BIOS/memcpy/inline/DMA copy hypotheses, and complete
  position-independent routine matching for changing stack addresses.
- Bounded BIOS/DMA copies with verified code also get native instruction entries
  for computed jumps. Large functions split at instruction boundaries, and C
  source units use a byte budget to keep host compilation within ordinary memory.
- Input-bound runtime coverage feedback. Re-exporting with `--feedback` translates
  newly observed code, with ROM checksums and source-file preservation checks.
- Instruction-boundary scheduler updates keep timer, DMA and audio accesses synchronized
  with translated instructions. The original timer fixture agrees with the reference CPU.
- Bounded ROM signatures recover short read-only Thumb helpers placed beside changing
  stack data. Guard-rejected code is included in miss reports; mixed ARM/Thumb entries
  in one copied image share the same byte-guard span.
- Independent translation views recover temporal and overlapping RAM copies, including
  multiple bodies at one address. Dispatch and each emitted native body check its own
  full ROM-backed footprint; direct calls into RAM use guarded runtime dispatch.
- Coverage retains distinct address/mode/source variants and caches repeated signatures.
- Load bus phases precede peripheral sampling. Three original ARM timer programs
  match independent mGBA observations (7, 13 and 103 ticks). Timer prescalers, cascades,
  reload/IRQ boundaries, acknowledgement and stopped-counter behavior are checked.
- RTC serial transfers require rising clock edges and honor chip-select aborts.
  Original cases cover repeated GPIO writes, midnight, leap days, months and years.
- Optional owner BIOS execution handles software interrupts, its IRQ vector and
  BIOS callbacks, including the protected ARM/Thumb instruction-prefetch latch;
  original firmware fixtures check ARM/Thumb supervisor entry and return. Built-in
  unsupported sound services fail explicitly. MultiBoot returns a disconnected-cable
  failure; link play is not implemented.
- An owner-supplied BIOS passes original fixed-rate, resampled and one-shot sound
  cases through generated native cartridge code. Checks cover sound mode, pitch,
  jump tables, IRQ/music callbacks, stereo mixing, clearing and VSync off/on.
  Native/reference PCM is identical; independent mGBA agrees on the active mixer
  buffers and selected service results. Firmware is never downloaded; an explicitly
  supplied image produces private firmware-derived source and initial data.
- Original CC0 fixture qualification and a required Windows/Linux native CI workflow.

The desktop export is registered in the GUI, application API and chat tool. OpenGL
3.3 rasterizes raw per-scanline tile/sprite/palette state at the current drawable
size. It preserves the original art's pixel detail. The CPU reference framebuffer
is used only for comparison or explicitly reported software compatibility mode.
The active monitor controls the initial window; F11 uses its native fullscreen size.
Keyboard/gamepad controls, paced stereo audio and atomic raw saves are included.
The pinned SDL 3.4.10 source downloads automatically during host configuration.

Emerald's 18,800-frame scripted run creates a character, reaches the overworld,
saves on the ground floor, sets the bedroom clock, and saves again. Fresh boots
return to the latest saved room. Advancing the configured RTC by one hour advances
the displayed clock hand by one hour. The feedback export contains 3,847 dispatch
entries, including 63 independently guarded RAM bodies. The complete scripted run
and the tested fresh-load clock paths pass strict static mode with zero interpreted
cycles. The two previously interpreted overlapping copies now execute native code.

Fresh-load date-change checks observe the game's own day counter, Birch daily state,
Mirage Island random value and berry-update timestamp. They advance when the date
advances. These are read-only observations of the generated game, with no game
hooks or RAM patches. Every result is bound to the exact owner-supplied revision.

The GPU images match the internal reference. A 900-frame native audio capture is
byte-identical to the reference CPU capture. Independently, mGBA 0.10.5 loads the
export's raw save and produces the same saved-room picture pixel for pixel. These
checks establish bounded compatibility, rather than a full gameplay acceptance test.
The owner reports all 18 original GPU scenes, resize/letterboxing checks and a
120-frame strict-native player run passing on an Intel Iris Xe GPU under Windows
11. The [physical-GPU summary](../gba-hardware-validation.json) records the
tested backend and scope. The retail tests in this workspace used llvmpipe and
SDL dummy audio; physical speakers, controllers and retail gameplay remain
owner-run. Retail measurements are in [gba-native-validation.json](../gba-native-validation.json).

CPU bus/prefetch timing remains approximate. The timer probes agree with mGBA for
both following-instruction layouts (MOV and a ROM-literal load). The earlier
two-cycle difference came from mGBA loading a tiny fixture into multiboot EWRAM;
the regression cartridges prevent that heuristic. Original firmware also checks
ARM/Thumb protected reads, IRQ entry/return and a cartridge callback against mGBA.
BIOS sound-driver qualification uses an owner-supplied image and original samples;
it covers the documented fixture modes, rather than every game's audio behavior.

## Test a Windows GPU

Run from the current repository's extracted folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-gba-hardware.ps1
```

The script finds `uv` and Visual Studio's bundled CMake, downloads the pinned source
dependencies as needed, and builds an original standalone GBA project. No ROM or
BIOS is needed. It checks all 18 raw-state GPU scenes, pixel comparison, DPI-aware
resizing and letterboxing, then runs the generated native player for two seconds.
Do not close PowerShell during the initial build; it can take several minutes.

The final `hardware-assessment.json` is saved under the printed temporary output
folder, alongside logs and a GPU image. `hardware_qualified: true` requires both
graphics tests to pass and their actual OpenGL device names to match integrated or
discrete devices in the graphics driver's Vulkan inventory. Vulkan is used only
for this hardware identity check; the GBA renderer uses OpenGL. Unmatched devices
remain unverified. This assessment does not qualify physical audio or controllers.

`-CheckTools` checks tool discovery without building. The cross-platform developer
command is `python -m tools.qualify_gba_hardware /new/output-folder`; adding
`--allow-software` permits software-driver comparison while preserving a false
physical-hardware result for that driver. Existing output folders are preserved.

## Generate a desktop project

Install a host C/C++ compiler and [CMake](https://cmake.org/download/) 3.20 or newer.
Windows users can use [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
with **Desktop development with C++**. GBA generation discovers the Visual Studio
**C++ CMake tools for Windows** component when CMake is absent from PATH; a separate
CMake installer is unnecessary when that component is installed. The source SDK and verified toml++ header
download automatically on first generation. No original-game compiler is required
for native translation.

```sh
decomp pc gba-inspect /path/to/your/game.gba
decomp pc gba-native /path/to/your/game.gba /new/source-folder --experimental
cd /new/source-folder
python tools/extract_assets.py /path/to/your/game.gba
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel 2
./build/gba_pc
```

Visual Studio puts the executable in `build/Release/gba_pc.exe`. The generated README
explains controls, display settings, raw saves and diagnostic captures. An unprofiled
retail cartridge can have unresolved callbacks or RAM-installed routines. The
player stops on uncovered code. Its binary contains no interpreter or runtime
compiler; a bounded passing run still does not establish full-game compatibility.

`--profile reviewed.json` accepts schema `decomp.wtf.gba-profile/v1`, the exact
`input_sha256`, `entries` (`address`, `mode`) and `ram_code` (`rom`, `address`,
`size`, `mode`). Only aligned code backed by the original input is accepted.
It does not accept patches, replacement functions or arbitrary host source files.
RAM mappings may overlap: each copy is analyzed independently and executes only
while its own complete byte footprint matches.

For games requiring original firmware, including its sound driver, supply your
own 16 KiB BIOS during generation:

```sh
decomp pc gba-native /path/to/game.gba /new/source-folder --bios /path/to/gba_bios.bin --experimental
```

The exporter emits native ARM/Thumb firmware entries and initial data, with an
exact image identity. Those private firmware-derived files are selected
automatically at runtime; no separate BIOS file is needed by the built player.
An untranslated replacement image is rejected. Firmware is never downloaded.
The default remains BIOS-free. Original miniature firmware checks vectors,
protected reads and IRQ returns with zero interpreted cycles; an original
cartridge also checks the supplied BIOS's three sound-driver modes against the
reference interpreter and independently established mixer-buffer observations.
To repeat the latter with your own BIOS, see the [fixture commands](../../tests/fixtures/gba-native/README.md).
The independent comparison checks the BIOS mixer buffers; mGBA's final filtered
and resampled PCM is not expected to match this runtime's final PCM byte for byte.

To expand native coverage without title-specific patches:

```sh
cmake -S . -B build -DGBA_BUILD_REFERENCE=ON
cmake --build build --target gba_probe --config Release --parallel 2
./build/gba_probe --rom assets/game.gba --frames 900 --miss-log /new/coverage.txt
decomp pc gba-native /path/to/your/game.gba /new/source-with-feedback --feedback /new/coverage.txt --experimental
```

Build the new source project and compare its output with the previous run. Repeat
`--feedback` to combine runs. Feedback is bound to the original ROM hash, never
silently overwrites an existing log, and reports addresses that still use fallback.
Copied RAM code retains runtime byte checks; coverage feedback is not proof that
all gameplay paths are statically translated. Feedback may include `size=0x...` for
bounded short helpers; those spans must be aligned, backed by the owner ROM and no
longer than 32 bytes. Branching, writing and PC-relative helpers keep the longer
signature or remain interpreted.

## Remaining PC-game acceptance

- [x] Adaptive desktop window, gamepad/keyboard input and paced audio.
- [x] Actual GPU rasterization of GBA backgrounds/sprites/effects, compared with the
  reference PPU, with drawable-resolution sizing and reported software fallback.
- [x] Original Flash 128 KiB protocol, bank, erase, atomic save/reload and serial RTC
  time/advance execution checks. These are cartridge protocol checks, not retail save proof.
- [x] Emerald cartridge save/reload across fresh boots, including both save generations.
- [x] In-game clock setting and hour advancement across fresh boots.
- [x] Native/reference PCM equality and independent mGBA save/room comparison.
- [x] Daily-clock dispatch and game-owned day/Birch/Mirage/berry-update state checks.
- [x] Missed indirect/RAM entry feedback, temporal overlays and per-body byte guards.
- [x] Independent timer microchecks, timer IRQ/cascade boundaries and RTC calendar edges.
- [x] Optional owner BIOS software-interrupt/IRQ paths, original ARM/Thumb prefetch,
  protected-read and cartridge-callback checks, and a normal disconnected MultiBoot result.
- [x] Supplied-BIOS fixed-rate/resampled/one-shot mixing, stereo output, callbacks,
  channel clearing and native/reference PCM equality, with independent mixer checks.
- [ ] Exact bus/prefetch timing, broader peripheral compatibility, individual berry
  growth events and broader retail audio coverage.
- [ ] Optional reviewed import of matching ELF/symbol data.
- [x] App/GUI/CLI native-game export integration under the shared PC-output contract.
- [x] Owner-supplied Emerald revision: clean native build, boot, graphics/audio/input,
  save/reload, clock and fallback report.
- [x] Owner-reported Windows 11/Intel Iris Xe qualification of original GPU scenes,
  resizing/letterboxing and the strict-native standalone player.
- [ ] Physical audio/controller validation and eventual owner playthrough.

## Pokémon references

[pret/pokeemerald](https://github.com/pret/pokeemerald) reconstructs the original
Emerald cartridge (documented SHA-1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`).
Its function names, code layout and matching ELF can help analysis for that exact
revision. It builds a GBA ROM; a host runtime is still needed for PC output.
[pokefirered](https://github.com/pret/pokefirered) offers the same kind of reference
for its own verified revisions. These title projects are optional references;
the backend remains a general GBA translator.

Gamma Emerald is an Unreal Engine remake. The public
[Gamma toolkit](https://github.com/StonedModder/gammaEmerald-toolkit) identifies
Unreal 5.3/5.6 and works with that game's `.pak` files. It can inform presentation
ideas, but does not provide an original-cartridge ARM/Thumb runtime or general
GBA decompiler. No Gamma installation or assets are required here.

Historical agbcc matching/C++ work remains separate in [gba-cpp.md](../gba-cpp.md).
