# Future work and platform coverage

This index records the work remaining after v0.19.0 for **Nintendo, Xbox and
PlayStation consoles**, plus shared decompiler tooling for those consoles.
Closely related or speculative platforms share a qualification plan; each needs
its own implementation evidence before support can be claimed.

The active product priority is **Dragon Quest and Pokémon PC output**, beginning
with DQVII. Existing matching/reconstruction workflows do not generate PC ports.
The [PC-output scope](pc-output.md) records the platform gaps and backend
candidates; 100% byte-matching source recovery is not a prerequisite for static
recompilation. Syphon Filter 1/2/3 recovery is checkpointed separately. Exhaustive
DQVII matching is also paused at a private checkpoint; the next milestone is a
PC-backend proof, retaining targeted source recovery for specific porting needs.
[PR #26: Game Specific Source Recovery](https://github.com/OMGitsMatt45/decomp.wtf/pull/26)
records all six paused disc checkpoints separately from PR #4. Its public files
contain reviewed layouts and hashes; actual source/attempt history stays in the
verified private ZIPs accompanying the task.

**19 PRs remain open: 16 plan-only PRs, two platform implementation PRs and one
game-specific recovery checkpoint PR.** PS1
disc/overlay reconstruction is implemented in PR #4; the separate DSi
container foundation remains in PR #24. The other drafts cover four
implemented platform families, eleven missing console workflows and shared
decompiler engines without adding new platform implementation.

N64 PR #3 and DS PRs #1, #7 and #25 are merged into `main`. Their qualification
records describe the completed scope and remaining game-specific coverage.

## Implemented platform families

All seven families below have a working path on native Windows and Linux.
The work plans focus on remaining coverage and explicitly preserve released
compiler behavior. GB/GBC is an experimental assembly workflow.

| Family | Current workflow / remaining focus | Guide or work plan | PR status |
| --- | --- | --- | --- |
| Nintendo 64 | Reviewed layouts, mixed compiler profiles, module builds and rooms implemented; further game-specific coverage | [Guide](n64.md) | [#3](https://github.com/OMGitsMatt45/decomp.wtf/pull/3) merged |
| PlayStation | Combined multi-disc projects, 1,632 exact retail C/C++ functions, reviewed code/resource growth and HBD/CHD authoring | [Guide](psx-disc.md) | [#4](https://github.com/OMGitsMatt45/decomp.wtf/pull/4) implementation |
| PlayStation 2 | Whole-disc/overlay exports, exact source provenance, tool evaluation | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps2/docs/future/ps2.md) | [#5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5) draft |
| Game Boy Advance | Distinct ARM compiler path and ARM/Thumb interworking | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gba/docs/future/gba.md) | [#6](https://github.com/OMGitsMatt45/decomp.wtf/pull/6) draft |
| Nintendo DS | ARM9/ARM7 source links, protected modules and exact reconstruction; further game-specific coverage | [Qualification](future/nds.md), [ARM7 recovery](ds-arm7.md) | [#7](https://github.com/OMGitsMatt45/decomp.wtf/pull/7) and [#25](https://github.com/OMGitsMatt45/decomp.wtf/pull/25) merged |
| GameCube / Wii | Modules, data completion and linked-source coverage | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gc-wii/docs/future/gc-wii.md) | [#8](https://github.com/OMGitsMatt45/decomp.wtf/pull/8) draft |
| Game Boy / Game Boy Color | Mapper state, reviewed layouts and room synchronization | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gb-gbc/docs/future/gb-gbc.md) | [#9](https://github.com/OMGitsMatt45/decomp.wtf/pull/9) draft |

## DSi container foundation

[PR #24](https://github.com/OMGitsMatt45/decomp.wtf/pull/24) is a separate open
implementation PR. Its [container inspector and stored-range
extractor](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/dsi-container/docs/dsi.md)
validates structural metadata and preserves stored program bytes and opaque TWL
authentication fields. Original-container tests passed on native Windows and Linux.

Modcrypt decryption, authentication, DSi source recovery and whole-image rebuilding
remain future work. The ordinary DS importer continues to reject DSi-enhanced and
DSi-exclusive ROMs. This foundation does not establish full DSi game support.

## Missing platform workflows

These families lack a verified from-scratch importer/matcher/export pipeline.
Some already appear in public-project metadata or draft routing. That does not
establish raw-game support. Existing programs can provide analysis, assemblers
or fixture builds; custom format, mapper, ABI, matching and export adapters still
need implementation. Native package availability must be checked per tool.

| Family | Qualification / implementation focus | Work plan | Draft PR |
| --- | --- | --- | --- |
| NES / Famicom | 6502, cartridge headers, mappers and assembly exports | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-nes/docs/future/nes.md) | [#10](https://github.com/OMGitsMatt45/decomp.wtf/pull/10) |
| SNES / Super Famicom | 65816 state, ROM mapping and separate coprocessor targets | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-snes/docs/future/snes.md) | [#11](https://github.com/OMGitsMatt45/decomp.wtf/pull/11) |
| Nintendo 3DS | ARM code images, modules and exact compiler qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-3ds/docs/future/3ds.md) | [#12](https://github.com/OMGitsMatt45/decomp.wtf/pull/12) |
| Wii U | RPX/RPL, PowerPC ABI and module reconstruction | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-wii-u/docs/future/wii-u.md) | [#13](https://github.com/OMGitsMatt45/decomp.wtf/pull/13) |
| Switch / deferred Switch 2 | AArch64 NSO/NRO and compiler provenance; Switch 2 deferred | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-switch/docs/future/switch.md) | [#14](https://github.com/OMGitsMatt45/decomp.wtf/pull/14) |
| PSP | Allegrex/VFPU, ELF/PRX and period compiler builds | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-psp/docs/future/psp.md) | [#15](https://github.com/OMGitsMatt45/decomp.wtf/pull/15) |
| PlayStation Vita | ARM/Thumb-2 module formats and native tool availability | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-vita/docs/future/vita.md) | [#16](https://github.com/OMGitsMatt45/decomp.wtf/pull/16) |
| PlayStation 3 | Separate PPU and SPU format, ABI and compiler qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps3/docs/future/ps3.md) | [#17](https://github.com/OMGitsMatt45/decomp.wtf/pull/17) |
| Original Xbox | XBE, x86 and original MSVC qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-xbox/docs/future/xbox.md) | [#18](https://github.com/OMGitsMatt45/decomp.wtf/pull/18) |
| Xbox 360 | XEX, Xenon/VMX128 and compiler-pack verification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-xbox360/docs/future/xbox360.md) | [#19](https://github.com/OMGitsMatt45/decomp.wtf/pull/19) |
| Modern consoles | Separate PS4/PS5 and Xbox One/Series evidence gates | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-modern-consoles/docs/future/modern-consoles.md) | [#20](https://github.com/OMGitsMatt45/decomp.wtf/pull/20) |

## Decompiler engines and shared tooling

m2c and optional Ghidra currently produce source drafts. splat/spimdisasm,
luvdis, decomp-toolkit, ds-decomp and RGBDS have separate analysis or assembly
roles covered by the family plans. RetDec, Reko and radare2/rizin ecosystem
plugins are candidates to evaluate, not installed decompiler backends. A new
engine alone supplies neither a console importer nor the original compiler.

| Area | Remaining focus | Work plan | Draft PR |
| --- | --- | --- | --- |
| Decompiler engines | m2c/Ghidra improvements and optional engine evaluation | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-draft-backends/docs/future/draft-backends.md) | [#21](https://github.com/OMGitsMatt45/decomp.wtf/pull/21) |

Modern console families remain deferred until original fixtures, accessible
formats and exact compiler/build provenance exist. Their draft PR records
feasibility gates rather than claiming a ready implementation.

## Completed and superseded PRs

| PR | Status on main |
| --- | --- |
| [#3](https://github.com/OMGitsMatt45/decomp.wtf/pull/3) | N64 layouts, compiler profiles, module reflow/recompression, reviewed rooms and retail export fixes merged. |
| [#1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1) | Original encrypted DS, source-layout and ARM/Thumb fixes included through the history preserved by #7. |
| [#7](https://github.com/OMGitsMatt45/decomp.wtf/pull/7) | DS reconstruction, source links, native qualification and two-processor execution checks merged. |
| [#22](https://github.com/OMGitsMatt45/decomp.wtf/pull/22) | Supplied-ROM imports, exact exports, boot-utility workflows and cloud compiler execution fixes merged. |
| [#23](https://github.com/OMGitsMatt45/decomp.wtf/pull/23) | README manual-download links and optional agent prerequisites merged. |
| [#25](https://github.com/OMGitsMatt45/decomp.wtf/pull/25) | Decrypted DS rebuilds, ARM7 C/C++ recovery, DS Protect and unusual module layouts merged. |
| [#2](https://github.com/OMGitsMatt45/decomp.wtf/pull/2) | Closed unmerged as superseded by the released PS1 C/C++ toolchains and native Windows PS2 EE-GCC hosts. |

The [N64 qualification record](n64-validation.json) pins **167 required tests on
each native Windows/Linux host, with zero skips**. Five private retail cartridges
also rebuild byte for byte from clean exports; the [retail record](n64-retail-validation.json)
contains hashes, source-sample counts and limits. These results establish the
implemented matching and reviewed-layout workflows, not complete game source
recovery or a retail playthrough.

The supplied decrypted DS image's earlier 12-byte rebuild difference is resolved
by explicit decrypted-input handling. The [retail DS record](ds-retail-yv5p.md)
documents exact full-ROM reconstruction, source-linked ARM7 units and bounded
emulator execution. Further game coverage and eventual playthrough validation
remain separate from those results.

## Work-plan status

All 18 open PRs target `main`. The 17 draft plans are #4–6 and #8–21; #24 is the
open DSi container foundation. N64 #3 and DS #7 are completed merged work,
with further DS recovery and retail fixes included in #25.

Keep each work-plan PR in draft until its implementation and acceptance checks
are complete. Update its scope and description around the actual delivered
behavior when implementation begins.

[Historical PR-creation results](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/pr-maintenance-2026-10-21/docs/maintenance/pr-results.json)
and the [housekeeping run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39535792050)
record the initial draft creation and earlier cleanup. They predate the merged
DS/N64 work and the current status recorded above.

## Completion rules

Every implementation must preserve original compiler identity, target language,
strict code/data/relocation checks and any required full-image verification.
Use original public fixtures for automated tests and keep private game inputs
out of branches. Qualify versioned native Windows/Linux packages and licenses
before advertising support. A draft, disassembly, successful assembly round trip
or runnable static recompile is not evidence of recovered matching C/C++.

Do not merge a work-plan-only draft as a completed platform. Update its scope
and description around the actual implementation and validation when work
begins. See the [compiler completion record](compiler-completion.md) and
[GB/GBC boundaries](gameboy-assembly.md) for the current baseline.
