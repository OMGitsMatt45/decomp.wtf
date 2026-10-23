# decomp.wtf

A local workbench for matching game decompilation. Import a supported game or
continue an existing decomp project, give agents individual functions, and check
their C/C++ against the original machine code. A match requires exact bytes;
a useful draft alone does not count as a match.

This maintained fork adds native Windows compiler hosts, period C++ frontends
and a GB/GBC assembly workbench. The latest release is
[**v0.19.0**](https://github.com/OMGitsMatt45/decomp.wtf/releases/tag/v0.19.0).
The original MIT-licensed project by Sam Wolfs was archived at v0.10.6.
Use this repository's installers and releases for the maintained fork.

[Install](#install) · [Manual downloads](#downloads-you-install-yourself) ·
[Platforms](#platforms) · [Agents](#agents) ·
[Public decomps](#continue-a-public-decomp) · [Future work](docs/future-work.md) ·
[Releases](https://github.com/OMGitsMatt45/decomp.wtf/releases)

## Install

Supported hosts are **Windows 10/11 x86-64** and **Linux x86-64**. Windows runs
the app and supported tools directly, without WSL. macOS is not supported.
Toolchain downloads are pinned and checksum verified. IDO and CodeWarrior keep
an explicit license acceptance step.

### Windows

Download the Windows ZIP from [the latest release](https://github.com/OMGitsMatt45/decomp.wtf/releases/latest),
extract it, and double-click **`windows.cmd`**. A source checkout or extracted
source ZIP can be installed with the same launcher.

Alternatively, run in PowerShell:

```powershell
irm https://github.com/OMGitsMatt45/decomp.wtf/releases/latest/download/install.ps1 | iex
```

Setup manages Python through uv and creates the `decomp` command, a Start menu
entry and a desktop shortcut. Projects live in `%USERPROFILE%\Decomp`.
Close the app and rerun the installer to update. See
[Windows setup and troubleshooting](docs/windows.md) for compiler details,
agent prerequisites and migration from an older WSL installation.

### Linux

```sh
curl -fsSL https://github.com/OMGitsMatt45/decomp.wtf/releases/latest/download/install.sh | bash
```

The full compiler suite is checked on Ubuntu 24.04 x86-64. Downloaded MIPS
binutils needs glibc 2.38 or newer; older 32-bit compilers need `libc6-i386`.
Projects live in `~/Decomp`, or `$DECOMP_HOME`. Start with `decomp`; update from
Settings or with `decomp update`.

Fresh remote installs use this fork's releases. Local source installs use that
source, and Git checkouts retain their repository and branch update source.
The original upstream website still refers to the archived upstream release.

### Downloads you install yourself

The installers manage uv, Python 3.12 and the app's Python dependencies, including
Ninja. Basic setup downloads KMC GCC, m2c and objdiff. Other supported compilers
and tools download on demand or through **Compilers & tools**, which also handles
their toolchain dependencies and checksum checks. IDO and CodeWarrior require
you to accept their licenses there before downloading. Ghidra is an optional
download from the same page; its Java prerequisite is separate.

Install the following only for the features you choose:

| Download | When you need it |
| --- | --- |
| [Java 21+ JDK (Eclipse Temurin)](https://adoptium.net/temurin/releases/?version=21) | Optional Ghidra decompiler. Put `java` on PATH; check with `java -version`. |
| [Git for Windows](https://git-scm.com/downloads/win) / [Git for Linux](https://git-scm.com/downloads/linux) | Cloning public decomp projects. Claude Code on Windows also needs Git Bash. |
| [Node.js LTS, including npm](https://nodejs.org/en/download) | Optional agents installed through npm, such as the app's Codex CLI and opencode installation commands. |
| [Ollama](https://ollama.com/download) / [LM Studio](https://lmstudio.ai/download) | Optional local model server. Install one and download a model through it if you choose that provider. |
| [melonDS libretro core](https://github.com/libretro/melonDS) / [RetroArch core downloader](https://www.retroarch.com/?page=platforms) | Optional developer DS execution comparison with `tools/ds_boot.py`; see [DS qualification](docs/future/nds.md#execution-validation). Supply your own DS BIOS and firmware files. |
| [GNU Make](https://www.gnu.org/software/make/) and [GCC/C++](https://gcc.gnu.org/install/binaries.html), or [MSYS2 on Windows](https://www.msys2.org/) | Only when building the optional DS execution core from source. A downloaded core does not need these host build tools. |

On Linux, the installer also expects [curl](https://curl.se/download.html).
Older 32-bit compilers need your distribution's 32-bit runtime, such as
[libc6-i386 on Ubuntu 24.04](https://packages.ubuntu.com/noble/libc6-i386).
These host packages are installed through your distribution's package manager.
Public decomp repositories can require additional build tools; follow that
project's setup instructions.

## Platforms

These are the implemented **from-scratch** paths. Public repository builds have
separate requirements and do not imply a raw-game importer for that platform.

| Platform | Current workflow | Compilers / tools | Status |
| --- | --- | --- | --- |
| Nintendo 64 | [Reviewed layouts, C/C++ matching, exact cartridge exports and bounded shiftable builds](docs/n64.md) | KMC GCC 2.7.2; IDO 5.3 / 7.1 | Recommended |
| GameCube / Wii | Disc or DOL import, matching in a generated dtk-template project | CodeWarrior; decomp-toolkit; objdiff | Recommended |
| PlayStation | Disc or EXE import, C/C++ matching and [exact disc / overlay reconstruction](docs/psx-disc.md) | PS1 GCC 2.7.2 / 2.8.1 | Beta |
| PlayStation 2 | Disc or ELF import, C/C++ matching and exact payload / ELF export | Original EE-GCC 2.96 | Beta |
| Game Boy Advance | ROM import, C/C++ matching and exact ROM export | Normal / old agbcc Thumb backends | Beta |
| Nintendo DS | ROM import and matching in a generated ds-decomp project | CodeWarrior for DS; dsd; objdiff | Beta |
| Game Boy / Game Boy Color | Bank-aware import, assembly editing, local agent claims and exact ROM export | RGBDS 1.0.4 | Experimental assembly workflow |

The supported compiler paths run on native Windows and Linux. Compiler
availability does not guarantee that a particular game's compiler version,
layout or runtime is supported. Beta platforms have less real-game coverage.
GB/GBC verifies **SM83 assembly**, and does not recover C/C++.

Filesystem-free DS boot utilities use a native GNU ARM assembly workflow that
rebuilds the complete cartridge. GameCube/Wii utilities without a main DOL use
GNU PowerPC assembly to rebuild their extracted apploader, including Wii
update-only partitions. These paths report assembly coverage separately from
verified edits and retained base bytes; they do not recover C/C++ or rebuild a
disc container. Assembly-only GBA exports need ARM binutils, without agbcc.

Whole-project imports of encrypted DS games need your own 16 KiB ARM7 BIOS. Before starting the app, set
`DECOMP_ARM7_BIOS` to its path (`$env:DECOMP_ARM7_BIOS = 'C:\Games\arm7_bios.bin'`
in PowerShell, or `export DECOMP_ARM7_BIOS=/path/to/arm7_bios.bin` on Linux).
The importer retains a copy in the project's ignored `extract/arm7_bios.bin`
for subsequent builds; the ROM and BIOS stay outside the project's Git history.
For a ROM already decrypted for an emulator, select **Already decrypted for an emulator**
in the DS import form, or pass `--input-format decrypted` to the pilot CLI. That
explicit workflow preserves the supplied secure bytes and retained checksum
metadata without a BIOS. Automatic mode continues to reject failed decryption.
Unencrypted homebrew with a zero checksum also omits the BIOS during rebuilding.
For bounded import/draft probes from a checkout, see
`uv run python tools/ds_pilot.py --help`; keep its work directory outside the checkout.
The BIOS supplies the secure-area key table; C/C++ compilation itself does not
need it. See [ARM7 C/C++ recovery](docs/ds-arm7.md) for the project workflow.
The independent `tools/ds_arm7.py` inspector and isolated leaf checker also work
without ARM9 secure-area validation.

Important boundaries:

- PS2 exports verify the program payload, imported overlays and original main
  ELF envelope. Whole-disc and separate overlay ELF repacking remain future work.
- IDO 5.3 includes both SGI/EDG and classic cfront, including cross-unit template
  prelinking. IDO 7.1 retains its own frontend and backend.
- GBA's normal and old Thumb compilers have distinct restored C++ frontends.
  The separate agbcc ARM-mode compiler is not integrated.
- DS links finished ARM9 and ARM7 C/C++ source units after their code and data
  match and the complete ROM still verifies. ARM7 calls, globals and recognized
  runtime copied blocks use a separate ARM7TDMI build. Protected ARM7 modules
  use decoded references and exact re-encryption. Unfinished code retains
  original bytes. See [ARM7 recovery](docs/ds-arm7.md) and the
  [retail rebuild/execution record](docs/ds-retail-yv5p.md).
  DSi-enhanced/exclusive ROM containers are rejected explicitly: the pinned
  toolkit cannot preserve ARM9i/ARM7i programs and TWL authentication metadata.
  DSi-branded compiler versions can still compile ordinary DS source.
- GB/GBC retains unknown bytes from the owner's base ROM. An exact rebuild is
  not a completed disassembly. Mapper analysis, richer layouts and room layout
  synchronization remain unfinished.
- C++ frontend support does not supply a game's runtime libraries, exceptions,
  RTTI or startup code. Period dialects and original symbol linkage still apply.

Details: [compiler completion record](docs/compiler-completion.md),
[PS2](docs/ps2-cpp.md), [IDO](docs/ido-cpp.md), [PS1](docs/psx-cpp.md),
[GBA](docs/gba-cpp.md), [GB/GBC](docs/gameboy-assembly.md).
The application uses Python and browser JavaScript; the N64 analysis library
uses C++17. Host implementation language and recovered game language are
separate facts, documented in the compiler record.

NES, SNES, 3DS, Wii U, Switch, PSP, Vita and additional Xbox/PlayStation targets
are [future work](docs/future-work.md). The roadmap focuses on Nintendo, Xbox
and PlayStation consoles.

## How it works

1. **Import your game.** The app identifies supported inputs and discovers code
   and data using platform tools. Open the included **Demo Quest 64** to try an
   N64 project without supplying a commercial game.
2. **Work on functions.** Edit source yourself or let agents claim functions.
   They receive assembly, context, drafts and feedback from earlier attempts.
3. **Compile and compare.** Raw ROM projects link candidates at their original
   addresses and check bytes and relocations. Project builds use objdiff and
   their own compiler configuration. Accepted matches are retained.
4. **Export and rebuild.** Exports combine matched source with original assembly
   or retained base bytes, and check the rebuilt output against your copy.
   Matching progress is not the same as a complete source rebuild or a PC port.

The browser shows claims, attempts, source editors, diffs and progress. Shared
headers, renames, similar-function lookup, draft attempts and the permuter help
with matching. Generated GameCube/Wii projects can link finished source files
into the game after a successful whole-game check.

## Agents

**AI agents are optional.** You can edit source, compile, compare and export
without an agent or model account. decomp.wtf does not install agent clients.
If you want one, use its official installation instructions:
[Claude Code](https://code.claude.com/docs/en/setup),
[Codex CLI](https://github.com/openai/codex#installing-and-running-codex-cli),
[Antigravity CLI](https://antigravity.google/docs/cli), or
[opencode](https://opencode.ai/docs/).

Run `decomp connect` to configure an installed Claude Code, Codex, Antigravity
CLI or opencode client. Then ask it to work on a local game or project. Any MCP
client can use `decomp mcp`; the app also supports OpenAI-compatible model
endpoints, including local servers.

Agent CLIs need their own installation requirements and sign-in. Hosted models
use your provider account. The app runs locally; configured model providers
receive the context sent to them. Agent work and projects are not automatically
published upstream.

## Continue a public decomp

Paste a project's repository URL into the app and follow that project's setup
and contribution rules. The app clones it onto a local `decomp-wtf` branch,
uses its source tree and build, and judges supported objects with objdiff.
Accepted matches become local commits for review.

**decomp.dev retired its project directory on 2026-10-15.** Existing installs can
show their cached list; fresh installs should use repository URLs. There is no
live catalog of 245 projects to browse. A repository for another platform may
work through its own build even when that platform has no from-scratch importer.

## Decompile together

Supported project workflows can share claims and accepted work through a room
hosted on your own machine or server. Each member supplies the same game copy.
Open **Decompile together** in the app, or use `decomp host` / `decomp join`.
GB/GBC room layout synchronization remains future work; use its local workflow.

## Verification and development

The [v0.19.0 operational run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39531701023)
passed **482 Linux** and **460 Windows** core checks, with expected host-specific
and unavailable private-ROM skips recorded in CI. Separate GB/GBC jobs also
passed. [Release checks](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39532746401)
installed the built wheel on both hosts and checked the CLI, native analyzer,
local web API and Windows ZIP. Release assets include `SHA256SUMS`.
These results describe the tested release commit, not every later change.

```sh
uv sync --locked --dev
uv run decomp
uv run pytest
```

Integration tests need their platform toolchains and some use optional local
fixtures. The [operational workflow](.github/workflows/operational.yml) installs
required tools, runs the platform suites and rejects missing required coverage.
See [future work](docs/future-work.md) for draft PRs and completion criteria.

| Path | Purpose |
| --- | --- |
| `src/decompnet/rom/` | Readers, analysis and raw-game matching |
| `src/decompnet/app/` | Browser app, MCP tools, agents and rooms |
| `src/decompnet/forks/` | Existing-project integration and generated builds |
| `src/decompnet/toolchains.toml` | Pinned compiler and tool downloads |
| `native/n64/` | Native N64 analysis library |
| `tools/`, `tests/`, `projects/` | Build recipes, checks and original fixtures |
| `docs/` | Platform limitations, validation and release records |
| `site/public/` | Installers and website assets |

## Credits and license

Built on [splat](https://github.com/ethteck/splat),
[spimdisasm](https://github.com/Decompollaborate/spimdisasm),
[objdiff](https://github.com/encounter/objdiff),
[m2c](https://github.com/matt-kempster/m2c),
[Ghidra](https://github.com/NationalSecurityAgency/ghidra),
[decomp-toolkit](https://github.com/encounter/decomp-toolkit),
[ds-decomp](https://github.com/AetiasHax/ds-decomp),
[luvdis](https://github.com/aarant/luvdis),
[RGBDS](https://github.com/gbdev/rgbds) and community compiler work from
[decompals](https://github.com/decompals). Their licenses remain their own.

The app supplies no commercial game data. Use your own copies and follow each
project's license and contribution policy, including its policy on AI work.

[MIT](LICENSE) © 2026 Sam Wolfs. Original authorship and license are preserved.
Not affiliated with the console manufacturers or the projects credited above.
