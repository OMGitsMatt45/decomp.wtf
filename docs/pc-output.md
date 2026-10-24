# PC output for Dragon Quest and Pokémon

The product goal is a Windows-buildable source repository with a working console
runtime, similar to [DQIV Recompiled 1.5](https://github.com/GoldieLeGenie/DQIV-Recompiled/releases/tag/1.5).
DS now has an [experimental native adapter](nds-native-runtime.md) that generates
this repository structure from a ROM and builds translated ARM9/ARM7 C++ with a
source-shipped hardware runtime. Other platform workflows still target the
original console. General retail compatibility is not yet qualified.

The [archived upstream](https://github.com/i12bp8/decomp.wtf#platforms) also
describes its rebuildable project as a base for ports. Resetting to upstream
would remove importer, reconstruction and compiler improvements without adding
a PC execution backend. Keep this fork and its reviewed game facts.

## Scope and reusable work

| Target | Current from-scratch support | Route toward PC output |
| --- | --- | --- |
| DS | ARM9/ARM7 recovery and console reconstruction; experimental native PC generation | Pinned MIT DQ9-Decomp translation/runtime integration supplies graphics, audio, input, timing and saves. Compatibility and optional enhancements remain title-specific validation. |
| PS1 | Disc/EXE recovery, reviewed modules and combined multi-disc reconstruction carried into PR #28 | Evaluate a PS1 recompiler/runtime backend against DQVII, retaining both discs in one generated project. |
| GBA | ARM/Thumb matching and cartridge reconstruction | Prefer an existing title decompilation where available, then integrate a PC runtime or translation backend. Pokémon source projects already exist. |
| PS2 | EE program/ELF recovery and reconstruction | Requires a PC execution/runtime path covering the game's EE, IOP, vector-unit, graphics and audio behavior. Current support does not provide it. |
| 3DS | Planned; no qualified raw-game pipeline | Both game import/execution integration and a PC runtime are additional work. |
| Switch | Planned; no qualified raw-game pipeline | Both program/service integration and a PC runtime are additional work. |

For GBA Pokémon, [pokeemerald](https://github.com/pret/pokeemerald) and
[pokefirered](https://github.com/pret/pokefirered) provide existing source
projects. They build GBA ROMs, so they do not by themselves establish PC output.
Use their supported revisions and contribution rules rather than recovering
the same source again. For DS, DQIV's existing `game/` source, `native/` runtime
and Windows build are a concrete reference, not proof of a generic DS backend.

GB/GBC currently provides an assembly workflow; a native PC adapter remains
additional work. N64, GameCube and Wii are outside the redesigned product scope.

## Generated repository acceptance target

The deliverable follows DQIV Recompiled's repository model: game code and a native
platform layer build together into a PC game. The generated repository contains:

```text
README.md                 supported input revisions, prerequisites, build/run steps
CMakeLists.txt            host game executable and runtime targets
pc-project.json           pinned identities, original input hashes, execution model
game/                     host-buildable recovered or translated C/C++ game code
native/                   platform services and runtime integration source
cmake/                    pinned dependency and module/build configuration
tools/                    validate input and extract/rebuild the owner's assets
tests/                    original execution fixtures and applicable runtime checks
```

Game assets are extracted locally from the owner's input and excluded from Git.
The README identifies the expected input locations, output executable and save
directory. Pinned external dependencies must be obtainable through the documented
build. Title-specific bindings, patches and enhancements remain identifiable.

A clean checkout plus the documented inputs and prerequisites must build and run
the supported game. Generated C/C++ can retain translated addresses and machine
state where recovery is incomplete; readable original names are not required
before static translation can produce a working native project. Any remaining
interpreter or runtime-compilation path is declared in the execution model.

This structure is the platform adapters' acceptance target. The common host
fixture verifies export/build plumbing. The DS adapter additionally produces
and executes this structure through original ARM9/ARM7 programs, a hardware
fixture and a privately supplied DQV ROM. These are separate levels of evidence;
they do not certify every title or a full playthrough.

## First active platform: DS; DQVII retained for later PS1 integration

Start with the shared application contract and DS backend. Preserve the existing
DQVII imports, original hashes, HBD/archive work, reviewed
engine/VRAM module placements and recovered source. Evaluate
[PSXRecomp](https://github.com/RetroPortingToolKit/psxrecomp) as an optional
backend rather than assuming we must build all PS1 hardware services ourselves.
Its documentation describes generated C, a shared PS1 runtime, streamed overlays
and multi-disc project setup. It is a beta dependency candidate; it has **not**
been built or qualified for DQVII in decomp.wtf.

Before integration, review and pin the framework and dependency revisions,
licenses, execution model and generated-project interfaces. Prove an original
fixture through generation, a clean Windows build and execution. Then adapt the
reviewed DQVII module facts and ordered two-disc set into one PC project. Verify
boot/title/menu, rendering, audio, input, saves/reloads, field/battle modules and
disc switching. The user handles the eventual full playthrough.

Any interpreter fallback or runtime code compilation must be visible in the
execution report. A hybrid runtime can be useful but must not be called a fully
static native build. A scaffold or successful CMake configure is not a playable
port; ship/runtime claims require execution evidence.

Keep PC-project export separate from matching-console export. Byte-identical
matching measures source recovery; PC qualification measures a host build and
working runtime. Static recompilation can translate unresolved machine code
without first recovering every function into readable, byte-matching C/C++.
Exhaustive DQVII source-matching passes are paused at a verified private checkpoint,
recorded alongside Syphon Filter in [PR #26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26).
Resume
targeted source recovery when it enables hooks, fixes or understanding
of a runtime failure, rather than making 100% matching a prerequisite for a port.

The redesign removes N64, GameCube and Wii application workflows; their prior
implementation is preserved in PR #27. Low-level shared MIPS helpers and old
qualification records do not advertise those platforms as supported.

One decomp.wtf fork can contain these optional adapters and pinned dependencies.
They do not require another fork of decomp.wtf per console. Validate one game
and backend first, then broaden to other Dragon Quest and Pokémon titles.


## Implemented shared contract

`decompnet.pc` defines a PC backend adapter and atomic project export. Each
adapter writes `pc-project.json` with schema `decomp.wtf.pc-project/v1`, a
remaining platform, pinned backend and runtime identities, ordered SHA-256 input
identities, `native-source`/`static-recompiled`/`hybrid` execution, a CMake target,
source-file hashes and explicit interpreter/runtime-compilation fallback flags.
Integrity verification does not claim a successful build or gameplay. Existing
output directories are preserved; invalid staged output is discarded.

`decomp pc status --platform nds` reports availability. `decomp pc verify PATH`
checks a generated project. Application project overviews expose PC capabilities
separately from matching-console reconstruction. The DS hardware adapter is
registered as experimental. Capability inspection does not install tools;
generation installs its pinned source dependencies automatically.

PR #29 retains the smaller [DS static generator](nds-pc.md) for original CPU
comparison fixtures and adds the [hardware adapter](nds-native-runtime.md) for
native repositories. The latter is available from DS import, the Source tab and
`decomp pc nds-native`. Its tests build and run graphics, audio, IRQ/input/IPC,
overlay loading and cartridge-save behavior on Windows/Linux. DQV source
generation, standalone building, boot/menu/field operation and initial save
interoperability have also been observed. GPU geometry rendering uses the
current drawable resolution and adapts to window/monitor changes. The optional
unified camera extends submitted 3D scenery over one picture, with accessible
secondary-screen UI and conservative native-screen fallbacks. Original GL and
guest fixtures qualify this presentation path. Further gameplay acceptance
belongs to the user. Optional mobile assets and other game-specific extras are
deferred to later output enhancement work.
