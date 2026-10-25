# GBA native PC output — PR6

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
- Headless frame/PCM capture, input, RAM observations, raw save persistence and a
  reference-interpreter mode. Interpreter use is reported and strict mode rejects it.
- Input-bound runtime coverage feedback. Re-exporting with `--feedback` translates
  newly observed code, with ROM checksums and source-file preservation checks.
- Instruction-boundary scheduler updates keep timer, DMA and audio accesses synchronized
  with translated instructions. The original timer fixture agrees with the reference CPU.
- Bounded ROM signatures recover short read-only Thumb helpers placed beside changing
  stack data. Guard-rejected code is included in miss reports; mixed ARM/Thumb entries
  in one copied image share the same byte-guard span.
- Unsupported BIOS sound/link services fail explicitly; they never silently return success.
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
the displayed clock hand by one hour. The feedback export contains 3,530 translated
functions; two overlapping RAM copies retain guarded interpreter fallback.

The GPU images match the internal reference. A 900-frame native audio capture is
byte-identical to the reference CPU capture. Independently, mGBA 0.10.5 loads the
export's raw save and produces the same saved-room picture pixel for pixel. These
checks establish bounded compatibility, rather than a full gameplay acceptance test.
This workspace uses llvmpipe software OpenGL and SDL dummy audio; physical GPU,
speakers and controller acceptance remain owner-run. Measured results and scope are
in [gba-native-validation.json](../gba-native-validation.json).

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
hybrid runtime reports fallback; a bounded run is not a gameplay acceptance test.

`--profile reviewed.json` accepts schema `decomp.wtf.gba-profile/v1`, the exact
`input_sha256`, `entries` (`address`, `mode`) and `ram_code` (`rom`, `address`,
`size`, `mode`). Only aligned code backed by the original input is accepted.
It does not accept patches, replacement functions or arbitrary host source files.

To expand native coverage without title-specific patches:

```sh
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
- [ ] Broader timing accuracy and RTC-driven daily gameplay events.
- [ ] Reviewed import of matching ELF/symbol data and missed indirect/RAM code discovery.
- [x] App/GUI/CLI native-game export integration under the shared PC-output contract.
- [x] Owner-supplied Emerald revision: clean native build, boot, graphics/audio/input,
  save/reload, clock and fallback report.
- [ ] Physical GPU/audio/controller validation and eventual owner playthrough.

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
