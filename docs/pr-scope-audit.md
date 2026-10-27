# Pull request index

Current through **PR #41**. The shared native-PC-output milestone is implemented
for DS, PS1, PS2, GBA and 3DS; the [roadmap](future-work.md) describes current
scope and per-game validation. Open preservation drafts are not unfinished
requirements for that milestone.

## Implemented milestones

| Area | Merged pull requests |
| --- | --- |
| Application contract and console scope | [#28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28), [#33](https://github.com/OMGitsMatt45/decomp.wtf/pull/33), [#35](https://github.com/OMGitsMatt45/decomp.wtf/pull/35) |
| DS native output and follow-up | [#29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29), [#36](https://github.com/OMGitsMatt45/decomp.wtf/pull/36), [#38](https://github.com/OMGitsMatt45/decomp.wtf/pull/38) |
| PS1 native output | [#30](https://github.com/OMGitsMatt45/decomp.wtf/pull/30), [#40](https://github.com/OMGitsMatt45/decomp.wtf/pull/40) |
| PS2 native output | [#5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5), [#31](https://github.com/OMGitsMatt45/decomp.wtf/pull/31), [#32](https://github.com/OMGitsMatt45/decomp.wtf/pull/32), [#41](https://github.com/OMGitsMatt45/decomp.wtf/pull/41) |
| GBA native output | [#6](https://github.com/OMGitsMatt45/decomp.wtf/pull/6), [#39](https://github.com/OMGitsMatt45/decomp.wtf/pull/39) |
| 3DS native output and physical GPU record | [#34](https://github.com/OMGitsMatt45/decomp.wtf/pull/34), [#37](https://github.com/OMGitsMatt45/decomp.wtf/pull/37) |

Earlier PR descriptions retain their original validation as historical evidence.
Later linked milestones establish current behavior: DS/3DS retain both original
screens; GBA/PS1/PS2 normal players do not fall back to instruction interpretation.

## Preserved drafts

| PR | Purpose | Current status |
| --- | --- | --- |
| [#24](https://github.com/OMGitsMatt45/decomp.wtf/pull/24) | DSi container inspection and stored-range extraction | Deferred draft with real implementation; no DSi native backend or current scope expansion |
| [#26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26) | Game Specific Source Recovery | Paused layouts/inventories and private-source checkpoints; preserve independently of native export |
| [#27](https://github.com/OMGitsMatt45/decomp.wtf/pull/27) | Preserve pre-redesign main | Identical-tree reference snapshot; no pending implementation and no merge into current main intended |

## Superseded planning drafts

- [#12](https://github.com/OMGitsMatt45/decomp.wtf/pull/12): closed in favor of
  implemented 3DS work in #34 and #37.
- [#21](https://github.com/OMGitsMatt45/decomp.wtf/pull/21): closed in favor of
  the shared contract in #28 and the five implemented native backends.

These proposals contained planning documents rather than additional runtime
implementation. Their branches and discussions remain available.

## Deferred console proposals

The following one-document planning PRs are closed as deferred references.
They do not add current console support. Revisit a proposal when implementation
for that console is requested, using the current PC-output contract.

| Proposal | PR |
| --- | --- |
| GB/GBC; functionality subsequently removed in #33 | [#9](https://github.com/OMGitsMatt45/decomp.wtf/pull/9) |
| NES / Famicom | [#10](https://github.com/OMGitsMatt45/decomp.wtf/pull/10) |
| SNES / Super Famicom | [#11](https://github.com/OMGitsMatt45/decomp.wtf/pull/11) |
| Wii U | [#13](https://github.com/OMGitsMatt45/decomp.wtf/pull/13) |
| Nintendo Switch | [#14](https://github.com/OMGitsMatt45/decomp.wtf/pull/14) |
| PSP | [#15](https://github.com/OMGitsMatt45/decomp.wtf/pull/15) |
| PlayStation Vita | [#16](https://github.com/OMGitsMatt45/decomp.wtf/pull/16) |
| PlayStation 3 | [#17](https://github.com/OMGitsMatt45/decomp.wtf/pull/17) |
| Original Xbox | [#18](https://github.com/OMGitsMatt45/decomp.wtf/pull/18) |
| Xbox 360 | [#19](https://github.com/OMGitsMatt45/decomp.wtf/pull/19) |
| PS4/PS5 and Xbox One/Series feasibility | [#20](https://github.com/OMGitsMatt45/decomp.wtf/pull/20) |

## Historical reconstruction work

Merged #1, #7, #22, #23 and #25 retain import/compiler/reconstruction work that
predates native output. Merged #3 records N64 functionality that was later
removed. Closed #2, #4 and #8 are superseded or retired; none needs reopening
for the current milestone. Their tested revisions remain historical evidence.

The [original migration audit](history/pr-migration-2026-10-23.md) preserves the
2026-10-23 titles and states. It is a historical snapshot, not the current backlog.
