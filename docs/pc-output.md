# PC output for Dragon Quest and Pokémon

The product goal is a Windows-buildable game project with a working console
runtime, similar to [DQIV Recompiled 1.5](https://github.com/GoldieLeGenie/DQIV-Recompiled/releases/tag/1.5).
**No existing from-scratch platform workflow in this fork currently generates
that output.** Native Windows toolchains run the decompilation tools; their
output still targets the original console.

The [archived upstream](https://github.com/i12bp8/decomp.wtf#platforms) also
describes its rebuildable project as a base for ports. Resetting to upstream
would remove importer, reconstruction and compiler improvements without adding
a PC execution backend. Keep this fork and its reviewed game facts.

## Scope and reusable work

| Target | Current from-scratch support | Route toward PC output |
| --- | --- | --- |
| DS | ARM9/ARM7 recovery and console reconstruction | Evaluate the existing DQIV source port/runtime for reuse; other titles still need their own program integration, overlays, graphics, audio, timing and saves. |
| PS1 | Disc/EXE recovery, reviewed modules and combined multi-disc reconstruction in PR #4 | Evaluate a PS1 recompiler/runtime backend against DQVII, retaining both discs in one generated project. |
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

The other existing families have the same boundary. N64 can evaluate
[N64Recomp](https://github.com/N64Recomp/N64Recomp) with
[N64ModernRuntime](https://github.com/N64Recomp/N64ModernRuntime); neither is
integrated here. GameCube/Wii requires a PowerPC execution and hardware runtime
or a title-specific source port. GB/GBC currently provides an assembly workflow,
not a PC exporter.

## First active target: DQVII

Keep the existing DQVII imports, original hashes, HBD/archive work, reviewed
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
Pause exhaustive DQVII source-matching passes at a private checkpoint. Resume
targeted source recovery when it enables hooks, fixes or understanding
of a runtime failure, rather than making 100% matching a prerequisite for a port.

One decomp.wtf fork can contain these optional adapters and pinned dependencies.
They do not require another fork of decomp.wtf per console. Validate one game
and backend first, then broaden to other Dragon Quest and Pokémon titles.
