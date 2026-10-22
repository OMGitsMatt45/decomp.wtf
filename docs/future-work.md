# Future work and platform coverage

This index records the work remaining after v0.19.0 for **Nintendo, Xbox and
PlayStation consoles**, plus shared decompiler tooling for those consoles.
Closely related or speculative platforms share a qualification plan; each needs
its own implementation evidence before support can be claimed.

**19 future-work PRs are open:** seven for implemented platform families,
eleven for missing console workflows, and one for shared decompiler engines.
Most documents are work plans with open implementation and validation checklists.
DS PR #7 includes implementation, original-fixture qualification and native
two-processor execution checks; further compatibility work stays explicit.

## Implemented platform families

All seven families below have a working path on native Windows and Linux.
The work plans focus on remaining coverage and explicitly preserve released
compiler behavior. GB/GBC is an experimental assembly workflow.

| Family | Remaining focus | Work plan | Draft PR |
| --- | --- | --- | --- |
| Nintendo 64 | Layouts, shiftable exports, IDO/KMC regression coverage | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-n64/docs/future/n64.md) | [#3](https://github.com/OMGitsMatt45/decomp.wtf/pull/3) |
| PlayStation | Disc and overlay reconstruction, compiler-specific parity | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps1/docs/future/ps1.md) | [#4](https://github.com/OMGitsMatt45/decomp.wtf/pull/4) |
| PlayStation 2 | Whole-disc/overlay exports, exact source provenance, tool evaluation | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps2/docs/future/ps2.md) | [#5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5) |
| Game Boy Advance | Distinct ARM compiler path and ARM/Thumb interworking | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gba/docs/future/gba.md) | [#6](https://github.com/OMGitsMatt45/decomp.wtf/pull/6) |
| Nintendo DS | Encrypted imports, verified source links and strict reconstruction/execution | [Qualification](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-nds/docs/future/nds.md) | [#7](https://github.com/OMGitsMatt45/decomp.wtf/pull/7) |
| GameCube / Wii | Modules, data completion and linked-source coverage | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gc-wii/docs/future/gc-wii.md) | [#8](https://github.com/OMGitsMatt45/decomp.wtf/pull/8) |
| Game Boy / Game Boy Color | Mapper state, reviewed layouts and room synchronization | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gb-gbc/docs/future/gb-gbc.md) | [#9](https://github.com/OMGitsMatt45/decomp.wtf/pull/9) |

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

## Existing PR cleanup

- [PR #2](https://github.com/OMGitsMatt45/decomp.wtf/pull/2) was closed as
  superseded. Released PS1 C/C++ toolchains and native Windows PS2 EE-GCC hosts
  replace its old compiler proposal and obsolete PS2-unavailable statement.
- [Draft PR #1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1) remains open.
  Its encrypted DS import, source-unit layout and ARM/Thumb fixes are absent
  from main; PR #7 preserves its implementation history and qualifies original
  fixtures on current Windows/Linux paths. The reported retail-ROM
  secure-prefix/checksum differences still need a strict full-ROM resolution.

## Work-plan status

All 19 PRs target `main`. The 18 work-plan branches remain in draft; DS PR #7 is
ready for review on the agreed original fixtures. Most branches contain a scoped
work-plan document with current coverage, reusable programs, missing work and
native Windows/Linux acceptance checks. DS PR #7 now includes implementation
and original-fixture and execution qualification, preserving PR #1's commit and review history;
its remaining retail-ROM and broader reconstruction gaps stay explicit.

[Verified creation results](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/pr-maintenance-2026-10-21/docs/maintenance/pr-results.json)
record the open drafts and the earlier PR cleanup. The
[housekeeping run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39535792050)
completed after the repository's PR-creation permission was enabled.

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
