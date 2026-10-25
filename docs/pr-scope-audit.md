# PR scope audit: DS-first PC output

Audited all 26 pre-existing open and closed PRs on 2026-10-23. Each PR description
now distinguishes historical console matching/reconstruction from native PC game
output. Open platform plans were retitled where needed; unrelated future plans
are deferred without claiming new support.

This is the historical migration snapshot, including titles and states at the
audit date. Subsequent DS/PS1 merges and experimental PS2 implementation are
tracked in the [current roadmap](future-work.md) and platform guides.

- [#27](https://github.com/OMGitsMatt45/decomp.wtf/pull/27) preserves main at
  `f965c3d783415b4c0d89ea49827760b4d9cab54c` with an identical Git tree and one
  empty snapshot commit. No implementation is merged by creating that PR.
- [#28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28) is the application
  redesign: remove N64/GameCube/Wii functionality and supply a shared PC-output
  contract. It carries forward #4's shared PS1 implementation commits. Merged
  into main on 2026-10-23 UTC at `acacecf517100d8bb49018d41360c0a97ed1a21b`.
- [#29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29) merged the experimental
  DS static translator, hardware runtime, application export integration and
  adaptive GPU presentation at `9b5440283bd90472edc029d4a1be3f8cfd1ad661`.
  Original fixtures and targeted DQV execution qualify its documented scope;
  full playthrough acceptance remains with the user.
- [#30](https://github.com/OMGitsMatt45/decomp.wtf/pull/30) begins PS1 native
  output with an optional pinned runtime assessment and original native CPU
  proof. Full hardware, ordered two-disc and DQVII integration remain open.
- #4 is closed as superseded by #28; #8 is closed because its consoles are removed.
  Their branches/review history are preserved. #26 is retargeted onto #28's branch
  and retains the paused game-specific source checkpoints privately.
- Merged DS PRs #1/#7/#25 cannot be reopened; #29 records the new scope. Unmerged
  #2 remains closed because later compiler work superseded it. No closed PR needed
  reopening for this migration.
- #5 is pending dedicated PS2 work, not a completed native PC backend. #6 targets
  GBA native output and existing Pokémon sources. #12/#14 remain planned 3DS/Switch
  import/runtime work; their raw-game pipelines are not implemented. #21 now
  prioritizes native adapters/code generation and execution qualification.

| PR | State after audit | Title at audit |
| --- | --- | --- |
| [#1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1) | Merged history | Fix encrypted DS imports, source splits, and Thumb autopilot |
| [#2](https://github.com/OMGitsMatt45/decomp.wtf/pull/2) | Closed / superseded | Add native Windows PS1 GCC 2.8.1 and track PS2 compiler support |
| [#3](https://github.com/OMGitsMatt45/decomp.wtf/pull/3) | Merged history | N64: mixed compiler profiles, module reflow and reviewed rooms |
| [#4](https://github.com/OMGitsMatt45/decomp.wtf/pull/4) | Closed / superseded | PlayStation: multi-disc projects, retail recovery and HBD/CHD authoring |
| [#5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5) | Open | PS2 PC output: native project backend and EE/IOP/VU runtime |
| [#6](https://github.com/OMGitsMatt45/decomp.wtf/pull/6) | Open | GBA PC output: reuse Pokemon source projects and add a native backend |
| [#7](https://github.com/OMGitsMatt45/decomp.wtf/pull/7) | Merged history | Fix DS reconstruction and qualify verified source-linked execution |
| [#8](https://github.com/OMGitsMatt45/decomp.wtf/pull/8) | Closed / superseded | [Future work] GameCube and Wii: expand linked-source and module coverage |
| [#9](https://github.com/OMGitsMatt45/decomp.wtf/pull/9) | Open | [Deferred] Game Boy and Game Boy Color: finish mapper and shared layouts |
| [#10](https://github.com/OMGitsMatt45/decomp.wtf/pull/10) | Open | [Deferred] NES and Famicom: add a mapper-aware assembly workbench |
| [#11](https://github.com/OMGitsMatt45/decomp.wtf/pull/11) | Open | [Deferred] SNES and Super Famicom: add 65816 assembly reconstruction |
| [#12](https://github.com/OMGitsMatt45/decomp.wtf/pull/12) | Open | 3DS PC output: import pipeline, execution backend and runtime |
| [#13](https://github.com/OMGitsMatt45/decomp.wtf/pull/13) | Open | [Deferred] Wii U: qualify PowerPC executable and module matching |
| [#14](https://github.com/OMGitsMatt45/decomp.wtf/pull/14) | Open | Switch PC output: AArch64 program integration and native runtime |
| [#15](https://github.com/OMGitsMatt45/decomp.wtf/pull/15) | Open | [Deferred] PSP: add Allegrex-aware executable and module workflows |
| [#16](https://github.com/OMGitsMatt45/decomp.wtf/pull/16) | Open | [Deferred] PlayStation Vita: qualify ARM module reconstruction |
| [#17](https://github.com/OMGitsMatt45/decomp.wtf/pull/17) | Open | [Deferred] PlayStation 3: qualify PPU and SPU as separate targets |
| [#18](https://github.com/OMGitsMatt45/decomp.wtf/pull/18) | Open | [Deferred] Original Xbox: qualify XBE and compiler-specific project builds |
| [#19](https://github.com/OMGitsMatt45/decomp.wtf/pull/19) | Open | [Deferred] Xbox 360: qualify Xenon code and XEX reconstruction |
| [#20](https://github.com/OMGitsMatt45/decomp.wtf/pull/20) | Open | [Deferred] Modern consoles: record PS4/PS5 and Xbox One/Series feasibility gates |
| [#21](https://github.com/OMGitsMatt45/decomp.wtf/pull/21) | Open | PC-output tooling: native backend adapters, code generation and qualification |
| [#22](https://github.com/OMGitsMatt45/decomp.wtf/pull/22) | Merged history | Fix supplied-ROM imports, exact exports, and cloud compiler execution |
| [#23](https://github.com/OMGitsMatt45/decomp.wtf/pull/23) | Merged history | Document manual downloads and optional agent prerequisites |
| [#24](https://github.com/OMGitsMatt45/decomp.wtf/pull/24) | Open | Begin DSi support with container inspection and stored-range extraction |
| [#25](https://github.com/OMGitsMatt45/decomp.wtf/pull/25) | Merged history | Fix decrypted DS rebuilds and recover protected ARM7 C/C++ modules |
| [#26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26) | Open | Game Specific Source Recovery |

At the audit checkpoint, main included the authorized PR #28 and #29 merges;
PR #27 preserves the earlier application. PS1 integration was the next active phase.
Historical qualification records apply to their tested revisions; they do not
qualify the redesigned application's future PC backends. The native export UI
stays unavailable on a platform until a real adapter is registered.

