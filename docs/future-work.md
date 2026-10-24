# DS-first native PC output

The goal is a Windows-buildable game project with a console runtime and output
similar to DQIV Recompiled. The previous matching/reconstruction application is
preserved unchanged in [PR #27](https://github.com/OMGitsMatt45/decomp.wtf/pull/27).
N64, GameCube and Wii are removed from application functionality in the redesign.

## Shared application phase

Merged in [PR #28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28), commit
`acacecf517100d8bb49018d41360c0a97ed1a21b`:

- Enforce the remaining platform scope at imports, public projects, saved
  project access, CLI, UI, setup and agent entry points without deleting data.
- Separate console reconstruction from native PC export in capabilities and
  project status. Matching progress is never a PC-port readiness measure.
- Introduce one PC-project adapter contract: pinned backend/runtime, ordered
  original input hashes, host C/C++ sources and CMake target, integrity checks,
  explicit interpreter/runtime-code-generation fallback, and staged publication.
- Qualify the common contract with an original fixture that builds and executes
  on native Windows/Linux. That result does not qualify a console runtime.

## Platform phase: start with DS

[PR #29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29) implements the first
experimental DS static translator and standalone CMake repository generator.
Original ARM9/ARM7 programs execute as generated C++, communicate through RAM,
call Thumb code, switch overlays at one address and persist a RAM checkpoint.
Independent original-byte execution checks registers, flags and program output.
See [current commands and limits](nds-pc.md) and the [DS implementation plan](future/ds-native.md).

The additional [native hardware-runtime path](nds-native-runtime.md) integrates
retail module decoding, the pinned MIT DQ9-Decomp emitter/runtime, graphics,
audio, timing/IRQs, input and cartridge saves. Original guest programs exercise
those interfaces; retail DQV compatibility is being fixed and qualified. The
[DQIV runtime assessment](future/ds-runtime-assessment.md) remains a product
reference; no DQIV runtime or mobile OBB dependency is copied.
The generator is explicit CLI-only while general platform export stays disabled.
Then validate one chosen DQ or Pokémon title through boot/title/menu, field/battle,
audio, input and save/reload. Full playthrough remains with the user.

GBA, PS1 and PS2 follow the common contract with separate backends. Reuse existing
Pokémon source projects and suitable recompiler/runtime projects. PS1 retains one
project for the ordered disc set. 3DS and Switch remain planned and need import
and runtime integration as well. GB/GBC retains its assembly workbench; native PC
output is additional work. Other console plans are deferred.

## PR migration

The [PR scope audit](pr-scope-audit.md) records updates to all 26 pre-existing PRs.
The shared redesign merged in [#28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28),
and [#29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29) tracks DS native output.

Merged PRs #1, #7 and #25 qualify DS console reconstruction, not PC output; merged
PR #3 is historical N64 work preserved by #27. Merged PRs cannot be reopened.
Unmerged PR #2 remains closed because its compiler work was superseded. PR #4's
shared PS1 fixes are carried into the redesign branch; source matching is paused
in #26. PR #8's GameCube/Wii expansion is superseded by the platform removal.

Active platform plans must be updated to depend on the shared PC-project contract
and require host-build/runtime evidence. Their previous matching-focused text is
historical scope, not proof of native output. See [PC-output details](pc-output.md).
