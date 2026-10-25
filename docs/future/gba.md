# GBA native PC output — PR6

Status: **implementation in progress; not a finished PC game backend**.
The goal is the same independent editable repository as DS/PS1/PS2: translated
game code, source-shipped hardware runtime, a desktop CMake build, adaptive GPU
presentation, audio, controllers, cartridge saves and explicit compatibility reports.

## Implemented foundation

- An input-validating `pc gba-inspect` command and experimental `pc gba-probe` exporter.
- ARMv4T ARM/Thumb discovery and native C translation through pinned MIT
  [AnyGBA](https://github.com/hoanglt1223/anygba/tree/a3eb412f79627eaae27e2523039d893f72dada1d).
- An independent C11/C++20 project containing translated code and the hardware core;
  the user's cartridge is staged privately by a SHA-256-verifying extraction script.
- Input-bound code profiles for callbacks and ROM-to-RAM code copies. Runtime byte
  checks prevent modified RAM code from executing stale native instructions.
- Headless frame/PCM capture, input, RAM observations, raw save persistence and a
  reference-interpreter mode. Interpreter use is reported and strict mode rejects it.
- Unsupported BIOS sound/link services fail explicitly; they never silently return success.
- Original CC0 fixture qualification and a required Windows/Linux native CI workflow.

The first probe has no desktop window or GPU renderer. Its CPU scanline PPU is a
reference for the GPU implementation, not fulfillment of the shared presentation
contract. Accordingly it stays outside registered PC-game backends and the GUI
does not advertise GBA native-game output yet. No retail ROM has been qualified.

## Reproduce the development probe

Install a host C/C++ compiler and [CMake](https://cmake.org/download/) 3.20 or newer.
Windows users can use [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
with **Desktop development with C++**. The source SDK and verified toml++ header
download automatically on first generation. No original-game compiler is required
for native translation.

```sh
decomp pc gba-inspect /path/to/your/game.gba
decomp pc gba-probe /path/to/your/game.gba /new/source-folder --experimental
cd /new/source-folder
python tools/extract_assets.py /path/to/your/game.gba
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel 2
./build/gba_probe --rom assets/game.gba --frames 8 --strict-static
```

Visual Studio puts the executable in `build/Release/gba_probe.exe`. An unprofiled
retail cartridge can have unresolved callbacks or RAM-installed routines. The
hybrid probe reports fallback; a bounded run is not a gameplay acceptance test.

`--profile reviewed.json` accepts schema `decomp.wtf.gba-profile/v1`, the exact
`input_sha256`, `entries` (`address`, `mode`) and `ram_code` (`rom`, `address`,
`size`, `mode`). Only aligned code backed by the original input is accepted.
It does not accept patches, replacement functions or arbitrary host source files.

## Remaining PC-game acceptance

- [ ] Adaptive desktop window, gamepad/keyboard input and paced audio.
- [ ] Actual GPU rasterization of GBA backgrounds/sprites/effects, compared with the
  reference PPU, with drawable-resolution sizing and reported software fallback.
- [ ] Broader timing, save-chip and RTC execution qualification, including Emerald's
  Flash 128 KiB cartridge and clock. Core presence is not retail proof.
- [ ] Reviewed import of matching ELF/symbol data and missed indirect/RAM code discovery.
- [ ] App/GUI/CLI native-game export integration under the shared PC-output contract.
- [ ] Owner-supplied Emerald revision: clean native build, boot, graphics/audio/input,
  save/reload, fallback report; eventual full playthrough remains with the owner.

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
