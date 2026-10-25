# decomp.wtf

A local game source-recovery workbench being refactored to generate buildable
PC source repositories for Dragon Quest and Pokémon. **DS and PS1 have experimental
native output; general retail compatibility is not qualified.** Existing console reconstruction remains available for the
remaining supported platforms.

[PR #27 preserves main](https://github.com/OMGitsMatt45/decomp.wtf/pull/27) exactly
at `f965c3d783415b4c0d89ea49827760b4d9cab54c`. N64, GameCube and Wii functionality
was removed in [PR #28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28). Existing project files are preserved, and
imports, public-project registration and old project execution reject those
platforms. Historical low-level helpers and qualification records are not claims
of current application support.

| Console | Source recovery / console reconstruction | Native PC output |
| --- | --- | --- |
| Nintendo DS | ARM9/ARM7, overlays and reviewed source links | Experimental static C++ and DS runtime; retail validation ongoing |
| PlayStation | EXE/discs, reviewed modules and combined multi-disc projects | Experimental native C, PS1 runtime, adaptive OpenGL and shared multi-disc build |
| PlayStation 2 | EE program/ELF recovery | Backend required |
| Game Boy Advance | ARM/Thumb recovery and ROM reconstruction | Backend required; reuse existing Pokémon sources |
| Game Boy / Game Boy Color | Assembly workflow | Backend required |
| Nintendo 3DS / Switch | Planned; no qualified raw-game pipeline | Additional import and runtime work |

## What the output means

A console export combines recovered source with unresolved original code and
rebuilds the console image. A PC export needs a separate code-generation adapter,
console runtime and host build. Matching percentages do not establish PC output.
Static recompilation does not require readable, byte-matching source for every
function first.

The new [PC-project contract](docs/pc-output.md) keeps backend/runtime revisions,
ordered input identities, source-file hashes, host build targets and fallback
behavior explicit. The application will not relabel a console export as a PC
port. DQIV Recompiled is the reference for the desired product, not an existing
generic DS backend in this application.

The target repository includes host-buildable game C/C++, a native runtime layer,
asset-extraction tools, pinned dependencies and build/run instructions. A clean
checkout with the documented original input should build the working PC game.

[PR #29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29) begins the DS backend
with an explicit [experimental generator](docs/nds-pc.md). Reviewed ARM/Thumb
instructions become C++ and execute with two CPU contexts and overlay switching.
The [native runtime path](docs/nds-native-runtime.md) also analyzes DS ROMs and
ships graphics, audio, input, timing and cartridge services as source. Original
programs verify rendering, sound, interrupts, IPC and real save reload. Retail
compatibility remains title-specific. DS import offers experimental PC generation
directly, without a matching compiler, and existing DS projects can export the
same native repository from the Source tab. Select the game's cartridge save
chip; DQV Europe defaults to the verified 64 KiB EEPROM configuration.

DS output also offers OpenGL rendering and an optional single-camera picture.
3D geometry renders at the current window/monitor resolution, adapting to
resizes and high-DPI changes. Fullscreen uses the active monitor's native
resolution. F6 switches the original screens/unified camera; F7 controls the
secondary-screen inset; F11 toggles fullscreen. The [guide](docs/nds-native-runtime.md)
describes native-screen fallbacks and per-title camera limits.

Generated DS projects use the DS ROM's assets and sound. Mobile OBB files are
not required. Optional mobile-remaster enhancements for DQ IV/V/VI are deferred,
with per-title mappings and an original-DS-audio option; they are not implemented
yet. BIOS and firmware are not runtime dependencies; an encrypted
original may need an owner-supplied ARM7 BIOS during initial decoding.

[PS1 output](docs/ps1-native.md) builds generated game C with a complete source
runtime: adaptive OpenGL geometry, audio, keyboard/gamepad input, CD-ROM and
shared memory cards. Ordered discs become one repository and executable; F9/F10
change the inserted disc. It uses bundled MIT OpenBIOS and needs no retail BIOS.
The optional pinned PSXRecomp dependency has **PolyForm Noncommercial** terms,
shown in the app and generated README/licenses. Execution is hybrid: recognized
code runs natively; unresolved or modified code is interpreted. Runtime guest-code
compilation is disabled. The shared GPU standard applies to all new game outputs;
PS1 uses one screen and DS retains its optional unified camera.

## Install and run

```sh
uv sync --locked --group dev
uv run decomp
uv run decomp pc status --platform nds
uv run decomp pc psx-native /path/to/game.m3u /path/to/new-source --experimental
uv run decomp pc verify /path/to/generated/pc-project
```

Linux and Windows host tools are supported. Agents are optional. Installers and
**Compilers & tools** manage Python dependencies and pinned supported compiler
packages; proprietary DS compiler downloads require license acceptance.

## Downloads you install yourself

Install the following only for the features you choose:

| Download | When you need it |
| --- | --- |
| [Java 21+ JDK (Eclipse Temurin)](https://adoptium.net/temurin/releases/?version=21) | Optional Ghidra decompiler. Put `java` on PATH; check with `java -version`. |
| [Git for Windows](https://git-scm.com/downloads/win) / [Git for Linux](https://git-scm.com/downloads/linux) | Cloning public decomp projects. Claude Code on Windows also needs Git Bash. |
| [Node.js LTS, including npm](https://nodejs.org/en/download) | Optional agents installed through npm, such as the app's Codex CLI and opencode installation commands. |
| [Ollama](https://ollama.com/download) / [LM Studio](https://lmstudio.ai/download) | Optional local model server. Install one and download a model through it if you choose that provider. |
| [MAME / chdman](https://www.mamedev.org/release.html) | Optional conversion of unsupported CHD variants or developer fixture regeneration. Supported CHD imports and mod builds need no external CHD tool. |
| [melonDS libretro core](https://github.com/libretro/melonDS) / [RetroArch core downloader](https://www.retroarch.com/?page=platforms) | Optional developer DS execution comparison with `tools/ds_boot.py`; see [DS qualification](docs/future/nds.md#execution-validation). Supply your own DS BIOS and firmware files. |
| [GNU Make](https://www.gnu.org/software/make/) and [GCC/C++](https://gcc.gnu.org/install/binaries.html), or [MSYS2 on Windows](https://www.msys2.org/) | Only when building the optional DS execution core from source. A downloaded core does not need these host build tools. |
| [Python](https://www.python.org/downloads/) | Standalone assets: 3.9+ for DS, 3.12+ for PS1. The main application uses Python 3.12+, managed by uv. |
| [CMake](https://cmake.org/download/) | Generated native builds: 3.20+ for DS, 3.24+ for PS1. Also required to generate PS1 C with its automatically built emitter. |
| [Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022) | Windows C/C++ host builds; select Desktop development with C++. A backend may instead qualify another host compiler. |
| Graphics drivers: [NVIDIA](https://www.nvidia.com/Download/index.aspx), [AMD](https://www.amd.com/en/support), [Intel](https://www.intel.com/content/www/us/en/download-center/home.html) | OpenGL GPU rendering in generated DS/PS1 projects. Use the driver for your card or your distribution's packages. Automatic mode reports software fallback; explicit OpenGL requires a working GPU context. |
| [DQ IV mobile](https://www.jp.square-enix.com/dqsp/dq4/en/), [DQ V mobile](https://www.jp.square-enix.com/dqsp/dq5/en/), [DQ VI mobile](https://www.jp.square-enix.com/dqsp/dq6/en/) | Optional future mobile-asset enhancements. Native DS output already uses the DS ROM; OBB playback/mappings are not implemented yet. |

On Linux, the installer also expects [curl](https://curl.se/download.html).
Older 32-bit compilers need your distribution's 32-bit runtime, such as
[libc6-i386 on Ubuntu 24.04](https://packages.ubuntu.com/noble/libc6-i386).
These host packages are installed through your distribution's package manager.
Public decomp repositories can require additional build tools; follow that
project's setup instructions. For generated PC projects on Linux, use your
distribution's GCC or Clang C++ package.

Linux windowed DS builds also need desktop graphics development libraries before
CMake builds SDL: [X11](https://packages.ubuntu.com/noble/libx11-dev),
[Xext](https://packages.ubuntu.com/noble/libxext-dev),
[OpenGL](https://packages.ubuntu.com/noble/libgl-dev) and
[EGL](https://packages.ubuntu.com/noble/libegl-dev). On Ubuntu/Debian:

```sh
sudo apt-get install build-essential libx11-dev libxext-dev libgl-dev libegl-dev
```

Use the equivalent development packages on other distributions. Headless DS
builds (`-DNDS_WITH_SDL=OFF`) do not need desktop graphics libraries.

PS1's pinned SDL3 additionally needs X11 extension and audio development packages:
[SDL3 Linux dependency guide](https://wiki.libsdl.org/SDL3/README-linux#build-dependencies).
Its generated README includes the complete Ubuntu/Debian install command.
SDL3, libchdr, libwebp and the PSXRecomp source archive download automatically;
they do not require separate manual downloads.

## Development and scope

The [roadmap](docs/future-work.md) separates shared application work from platform
backends and records the PR audit. Original fixtures exercise the PC-project
contract and DS static code generation with actual host builds and execution;
this is not DS retail execution:

```sh
uv run pytest -q tests/test_platform_scope.py tests/test_pc_output.py tests/test_nds_pc.py tests/test_nds_native.py tests/test_nds_native_app.py tests/test_nds_native_video.py
```

The DS workflow installs the pinned source runtime and requires SDL checks on
Windows/Linux plus OpenGL execution on Linux. See the [native guide](docs/nds-native-runtime.md)
for GPU qualification and conservative compatibility limits.

DS native output is merged in PR #29. [PS1 native output](docs/ps1-native.md)
is implemented in PR #30 with an original two-disc hardware fixture and a
Windows/Linux standalone build/execution workflow. DQVII is the first retail
target; boot checks and full playthrough acceptance remain distinct.

[PS2 native output](docs/future/ps2.md) is implemented experimentally in PR #5. Shared disc
and overlay discovery feed a standalone C++/CMake export with source-shipped
runtime, adaptive Vulkan geometry, audio, input and saves. Use `decomp pc ps2-native
GAME.iso NEW_OUTPUT --experimental`, or the GUI's native PC output. Exact-hash
profiles are selected automatically when bundled. Closed stripped programs can
be mapped automatically; ambiguous code and external callbacks need a reviewed
map. Windows/Linux qualification and retail acceptance are
reported separately; source generation alone does not certify a working port.

To validate PS2 output on your Windows GPU, use Visual Studio or
[Visual Studio Desktop C++ Build Tools](https://visualstudio.microsoft.com/downloads/)
with **Desktop development with C++**, including **C++ CMake tools for Windows**.
The wrapper finds Visual Studio's bundled CMake even when it is absent from PATH;
a separate [CMake installation](https://cmake.org/download/) is optional.
Install
[uv](https://docs.astral.sh/uv/getting-started/installation/) from PowerShell:

```powershell
winget install --id astral-sh.uv --exact
```

Close and reopen PowerShell so it sees the updated PATH. In File Explorer, open
the extracted repository folder containing `pyproject.toml` and `tools`, type
`powershell` into the address bar, press Enter, and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-ps2-hardware.ps1
```

The wrapper also finds uv in its standard user install folders if PATH has not
refreshed, and chooses a new output folder for each run. For a custom folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-ps2-hardware.ps1 -Output "$env:TEMP\decomp-ps2-gpu-my-test"
```

If PowerShell reports `uv is not recognized`, the test has not started; install uv
and reopen the shell. If WinGet is unavailable, use the linked official uv installer.
The command uses an original test program and reports the actual Vulkan device
class; software/virtual rendering does not count as physical-GPU validation.
The first run downloads and verifies pinned runtime sources, then compiles the
standalone fixture. Allow these steps to finish; they can take several minutes.
Progress messages identify verification and build stages. Completion prints the
`hardware-assessment.json` path. Stopping with Ctrl+C records an interrupted test;
retry with a new output folder.

Existing DS, PS1, GBA and GB/GBC qualification workflows retain their own scope.
The preserved branch contains previous N64/GameCube/Wii workflows. Private
retail sources and all failed recovery attempts are checkpointed in
[PR #26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26); only layouts and hashes
are public. Never commit original games, BIOS, SDK payloads or credentials.

[MIT](LICENSE), based on the archived original project by Sam Wolfs. This fork is
not affiliated with Nintendo, Sony or the original maintainer.
