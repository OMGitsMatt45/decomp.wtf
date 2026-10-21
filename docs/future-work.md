# Future work and platform coverage

This index records the work remaining after v0.19.0. It covers all implemented
platform families, relevant missing non-Sega families, and the draft decompiler
engines. Closely related or speculative platforms share a qualification plan;
each needs its own implementation evidence before support can be claimed.

**PR creation is pending.** The 21 reviewable work-plan branches below are
pushed, but GitHub rejected draft creation because this repository disables
pull requests created by GitHub Actions. The documents are plans, not new
platform implementations. No Sega consoles are included.

## Implemented platform families

All seven families below have a working path on native Windows and Linux.
The work plans focus on remaining coverage and explicitly preserve released
compiler behavior. GB/GBC is an experimental assembly workflow.

| Family | Remaining focus | Prepared work plan | Open PR form |
| --- | --- | --- | --- |
| Nintendo 64 | Layouts, shiftable exports, IDO/KMC regression coverage | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-n64/docs/future/n64.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-n64?expand=1&title=%5BFuture+work%5D+Nintendo+64%3A+expand+layouts+and+preserve+compiler+parity&body=Future-work+draft+for+%60docs%2Ffuture%2Fn64.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PlayStation | Disc and overlay reconstruction, compiler-specific parity | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps1/docs/future/ps1.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-ps1?expand=1&title=%5BFuture+work%5D+PlayStation%3A+broaden+disc+and+overlay+reconstruction&body=Future-work+draft+for+%60docs%2Ffuture%2Fps1.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PlayStation 2 | Whole-disc/overlay exports, exact source provenance, tool evaluation | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps2/docs/future/ps2.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-ps2?expand=1&title=%5BFuture+work%5D+PlayStation+2%3A+finish+disc+exports+and+qualify+additional+tooling&body=Future-work+draft+for+%60docs%2Ffuture%2Fps2.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Game Boy Advance | Distinct ARM compiler path and ARM/Thumb interworking | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gba/docs/future/gba.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-gba?expand=1&title=%5BFuture+work%5D+Game+Boy+Advance%3A+integrate+the+distinct+ARM+compiler+path&body=Future-work+draft+for+%60docs%2Ffuture%2Fgba.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Nintendo DS | Unfinished PR #1, encrypted imports and strict reconstruction | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-nds/docs/future/nds.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-nds?expand=1&title=%5BFuture+work%5D+Nintendo+DS%3A+resolve+encrypted+imports+and+reconstruction+gaps&body=Future-work+draft+for+%60docs%2Ffuture%2Fnds.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| GameCube / Wii | Modules, data completion and linked-source coverage | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gc-wii/docs/future/gc-wii.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-gc-wii?expand=1&title=%5BFuture+work%5D+GameCube+and+Wii%3A+expand+linked-source+and+module+coverage&body=Future-work+draft+for+%60docs%2Ffuture%2Fgc-wii.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Game Boy / Game Boy Color | Mapper state, reviewed layouts and room synchronization | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-gb-gbc/docs/future/gb-gbc.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-gb-gbc?expand=1&title=%5BFuture+work%5D+Game+Boy+and+Game+Boy+Color%3A+finish+mapper+and+shared+layouts&body=Future-work+draft+for+%60docs%2Ffuture%2Fgb-gbc.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |

## Missing platform workflows

These families lack a verified from-scratch importer/matcher/export pipeline.
Some already appear in public-project metadata or draft routing. That does not
establish raw-game support. Existing programs can provide analysis, assemblers
or fixture builds; custom format, mapper, ABI, matching and export adapters still
need implementation. Native package availability must be checked per tool.

| Family | Qualification / implementation focus | Prepared work plan | Open PR form |
| --- | --- | --- | --- |
| NES / Famicom | 6502, cartridge headers, mappers and assembly exports | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-nes/docs/future/nes.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-nes?expand=1&title=%5BFuture+work%5D+NES+and+Famicom%3A+add+a+mapper-aware+assembly+workbench&body=Future-work+draft+for+%60docs%2Ffuture%2Fnes.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| SNES / Super Famicom | 65816 state, ROM mapping and separate coprocessor targets | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-snes/docs/future/snes.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-snes?expand=1&title=%5BFuture+work%5D+SNES+and+Super+Famicom%3A+add+65816+assembly+reconstruction&body=Future-work+draft+for+%60docs%2Ffuture%2Fsnes.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Nintendo 3DS | ARM code images, modules and exact compiler qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-3ds/docs/future/3ds.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-3ds?expand=1&title=%5BFuture+work%5D+Nintendo+3DS%3A+qualify+ARM+image+and+project+integration&body=Future-work+draft+for+%60docs%2Ffuture%2F3ds.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Wii U | RPX/RPL, PowerPC ABI and module reconstruction | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-wii-u/docs/future/wii-u.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-wii-u?expand=1&title=%5BFuture+work%5D+Wii+U%3A+qualify+PowerPC+executable+and+module+matching&body=Future-work+draft+for+%60docs%2Ffuture%2Fwii-u.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Switch / deferred Switch 2 | AArch64 NSO/NRO and compiler provenance; Switch 2 deferred | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-switch/docs/future/switch.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-switch?expand=1&title=%5BFuture+work%5D+Nintendo+Switch%3A+qualify+AArch64+module+and+build+adapters&body=Future-work+draft+for+%60docs%2Ffuture%2Fswitch.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PSP | Allegrex/VFPU, ELF/PRX and period compiler builds | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-psp/docs/future/psp.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-psp?expand=1&title=%5BFuture+work%5D+PSP%3A+add+Allegrex-aware+executable+and+module+workflows&body=Future-work+draft+for+%60docs%2Ffuture%2Fpsp.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PlayStation Vita | ARM/Thumb-2 module formats and native tool availability | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-vita/docs/future/vita.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-vita?expand=1&title=%5BFuture+work%5D+PlayStation+Vita%3A+qualify+ARM+module+reconstruction&body=Future-work+draft+for+%60docs%2Ffuture%2Fvita.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PlayStation 3 | Separate PPU and SPU format, ABI and compiler qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-ps3/docs/future/ps3.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-ps3?expand=1&title=%5BFuture+work%5D+PlayStation+3%3A+qualify+PPU+and+SPU+as+separate+targets&body=Future-work+draft+for+%60docs%2Ffuture%2Fps3.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Original Xbox | XBE, x86 and original MSVC qualification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-xbox/docs/future/xbox.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-xbox?expand=1&title=%5BFuture+work%5D+Original+Xbox%3A+qualify+XBE+and+compiler-specific+project+builds&body=Future-work+draft+for+%60docs%2Ffuture%2Fxbox.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Xbox 360 | XEX, Xenon/VMX128 and compiler-pack verification | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-xbox360/docs/future/xbox360.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-xbox360?expand=1&title=%5BFuture+work%5D+Xbox+360%3A+qualify+Xenon+code+and+XEX+reconstruction&body=Future-work+draft+for+%60docs%2Ffuture%2Fxbox360.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| PC | Bounded PE/ELF targets and reproducible project builds | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-pc/docs/future/pc.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-pc?expand=1&title=%5BFuture+work%5D+PC%3A+qualify+executable+analysis+and+reproducible+matching+builds&body=Future-work+draft+for+%60docs%2Ffuture%2Fpc.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Other classic consoles | Atari, PC Engine, Neo Geo and other non-Sega legacy families | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-other-classic/docs/future/other-classic.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-other-classic?expand=1&title=%5BFuture+work%5D+Other+classic+consoles%3A+qualify+non-Sega+CPU+and+cartridge+families&body=Future-work+draft+for+%60docs%2Ffuture%2Fother-classic.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |
| Modern consoles | Separate PS4/PS5 and Xbox One/Series evidence gates | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-modern-consoles/docs/future/modern-consoles.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-modern-consoles?expand=1&title=%5BFuture+work%5D+Modern+consoles%3A+record+PS4%2FPS5+and+Xbox+One%2FSeries+feasibility+gates&body=Future-work+draft+for+%60docs%2Ffuture%2Fmodern-consoles.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |

## Decompiler engines and shared tooling

m2c and optional Ghidra currently produce source drafts. splat/spimdisasm,
luvdis, decomp-toolkit, ds-decomp and RGBDS have separate analysis or assembly
roles covered by the family plans. RetDec, Reko and radare2/rizin ecosystem
plugins are candidates to evaluate, not installed decompiler backends. A new
engine alone supplies neither a console importer nor the original compiler.

| Area | Remaining focus | Prepared work plan | Open PR form |
| --- | --- | --- | --- |
| Decompiler engines | m2c/Ghidra improvements and optional engine evaluation | [Plan](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/future-draft-backends/docs/future/draft-backends.md) | [Create draft](https://github.com/OMGitsMatt45/decomp.wtf/compare/main...codex/future-draft-backends?expand=1&title=%5BFuture+work%5D+Decompiler+engines%3A+strengthen+m2c%2FGhidra+and+qualify+alternatives&body=Future-work+draft+for+%60docs%2Ffuture%2Fdraft-backends.md%60.+The+branch+contains+the+current+baseline%2C+reusable+tools%2C+missing+implementation+and+native+Windows%2FLinux+acceptance+checks.+No+new+platform+support+is+implemented.+Keep+this+PR+in+draft+until+its+implementation+and+checks+are+complete.) |

The classic-console plan includes Atari 2600/5200/7800/Lynx/Jaguar, PC Engine /
TurboGrafx-16, Neo Geo, WonderSwan, Virtual Boy, Neo Geo Pocket, 3DO,
ColecoVision and Intellivision. These are separate feasibility targets, not one
generic implementation. Split a qualified family into its own implementation
PR before enabling it. Modern families remain deferred until original fixtures,
accessible formats and exact compiler/build provenance exist.

## Existing PR cleanup

- [PR #2](https://github.com/OMGitsMatt45/decomp.wtf/pull/2) was closed as
  superseded. Released PS1 C/C++ toolchains and native Windows PS2 EE-GCC hosts
  replace its old compiler proposal and obsolete PS2-unavailable statement.
- [Draft PR #1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1) remains open.
  Its encrypted DS import, source-unit layout and ARM/Thumb fixes are absent
  from main. Its reported secure-prefix/checksum differences still need a strict
  full-ROM resolution and current native Windows/Linux validation. The DS plan
  depends on reviewing this work rather than discarding it.

## Creating the prepared drafts

Each **Create draft** link opens a prefilled PR form for that plan. Choose
**Create draft pull request** in GitHub; the form alone does not open a PR.

For batch creation, the repository owner can enable **Settings → Actions →
General → Workflow permissions → Allow GitHub Actions to create and approve
pull requests**, then rerun the failed job in the
[prepared housekeeping run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39534893121).
The workflow exists only on `codex/pr-maintenance-2026-10-21`, not on main.
It uses the repository CI token, checks the reviewed branch/PR heads, preserves
PR #1, and creates one draft per work-plan branch. It checks existing open PRs
by branch before creating any, so a retry does not duplicate successful work.

The exact plan and PR bodies are retained in the
[maintenance manifest](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/pr-maintenance-2026-10-21/docs/maintenance/pr-plan.json).
[Operation results](https://github.com/OMGitsMatt45/decomp.wtf/blob/codex/pr-maintenance-2026-10-21/docs/maintenance/pr-results.json)
record the successful cleanup and the rejected creation attempt.

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
