# DS-first native PC output

The goal is a Windows-buildable game project with a console runtime and output
similar to DQIV Recompiled. The previous matching/reconstruction application is
preserved unchanged in [PR #27](https://github.com/OMGitsMatt45/decomp.wtf/pull/27).
N64, GameCube and Wii are removed from application functionality in the redesign.

## Shared application phase

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

First implement and qualify DS ARM9/ARM7 execution integration and its runtime,
including overlays, memory, graphics, audio, timing, input, files and saves.
Evaluate DQIV's native runtime/source as a reusable dependency after reviewing its
interfaces and license. Do not assume its title-specific implementation supports
another DQ or Pokémon title unchanged. Use original fixtures first, then validate
one chosen retail title through boot/title/menu, field/battle, audio, input and
save/reload. Full playthrough remains with the user.

GBA, PS1 and PS2 follow the common contract with separate backends. Reuse existing
Pokémon source projects and suitable recompiler/runtime projects. PS1 retains one
project for the ordered disc set. 3DS and Switch remain planned and need import
and runtime integration as well. GB/GBC retains its assembly workbench; native PC
output is additional work. Other console plans are deferred.

## PR migration

Merged PRs #1, #7 and #25 qualify DS console reconstruction, not PC output; merged
PR #3 is historical N64 work preserved by #27. Merged PRs cannot be reopened.
Unmerged PR #2 remains closed because its compiler work was superseded. PR #4's
shared PS1 fixes are carried into the redesign branch; source matching is paused
in #26. PR #8's GameCube/Wii expansion is superseded by the platform removal.

Active platform plans must be updated to depend on the shared PC-project contract
and require host-build/runtime evidence. Their previous matching-focused text is
historical scope, not proof of native output. See [PC-output details](pc-output.md).
