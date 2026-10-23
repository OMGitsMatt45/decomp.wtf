# decomp.wtf

A local game source-recovery workbench being refactored to generate buildable
PC source repositories for Dragon Quest and Pokémon. **DS is first. No retail PC-output backend
is qualified yet.** Existing console reconstruction remains available for the
remaining supported platforms.

[PR #27 preserves main](https://github.com/OMGitsMatt45/decomp.wtf/pull/27) exactly
at `f965c3d783415b4c0d89ea49827760b4d9cab54c`. N64, GameCube and Wii functionality
is removed on this redesign branch. Existing project files are preserved, and
imports, public-project registration and old project execution reject those
platforms. Historical low-level helpers and qualification records are not claims
of current application support.

| Console | Source recovery / console reconstruction | Native PC output |
| --- | --- | --- |
| Nintendo DS | ARM9/ARM7, overlays and reviewed source links | First backend to implement |
| PlayStation | EXE/discs, reviewed modules and combined multi-disc projects | Backend required |
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

## Install and run

```sh
uv sync --locked --group dev
uv run decomp
uv run decomp pc status --platform nds
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

On Linux, the installer also expects [curl](https://curl.se/download.html).
Older 32-bit compilers need your distribution's 32-bit runtime, such as
[libc6-i386 on Ubuntu 24.04](https://packages.ubuntu.com/noble/libc6-i386).
These host packages are installed through your distribution's package manager.
Public decomp repositories can require additional build tools; follow that
project's setup instructions.
| [CMake 3.20+](https://cmake.org/download/) | Building generated native PC projects and running the output-contract fixture. |
| [Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022) | Windows C/C++ host builds; select Desktop development with C++. A backend may instead qualify another host compiler. |

## Development and scope

The [roadmap](docs/future-work.md) separates shared application work from platform
backends and records the PR audit. Original fixture checks exercise the PC-project
contract with an actual host build/run; this is not DS retail execution:

```sh
uv run pytest -q tests/test_platform_scope.py tests/test_pc_output.py
```

Existing DS, PS1, GBA and GB/GBC qualification workflows retain their own scope.
The preserved branch contains previous N64/GameCube/Wii workflows. Private
retail sources and all failed recovery attempts are checkpointed in
[PR #26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26); only layouts and hashes
are public. Never commit original games, BIOS, SDK payloads or credentials.

[MIT](LICENSE), based on the archived original project by Sam Wolfs. This fork is
not affiliated with Nintendo, Sony or the original maintainer.
