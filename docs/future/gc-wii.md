# Future work: GameCube and Wii: expand linked-source and module coverage

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Disc/DOL import, generated dtk-template projects, CodeWarrior C/C++ matching, exact rebuilding and finished-file linking are implemented. Paths containing spaces and clean target builds were fixed for v0.19.0.

## Existing programs to reuse or qualify

Reuse pinned decomp-toolkit, dtk-template, CodeWarrior, objdiff and m2c. Existing native compiler binaries require the established explicit installation step.

## Work that remains

- [ ] Broaden REL/module relocation and cross-module data coverage using original fixtures.
- [ ] Expand file split, data completion and automatic source linking coverage across compiler versions.
- [ ] Audit disc container metadata and distinguish code matching, linked-source progress and full container rebuilding.

## Acceptance checks

- [ ] Exercise DOL and REL relocations, source splitting, shared data and automatic linking on both hosts.
- [ ] Require successful whole-game checks before retaining linked-file changes.
- [ ] Retain clean build, Ninja reconfiguration and compiler/tool paths containing spaces regressions.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/scratch_dtk.py`
- `src/decompnet/forks/dtksplits.py`
- `src/decompnet/app/forkengine.py`

## References

- [decomp-toolkit](https://github.com/encounter/decomp-toolkit)
- [dtk-template](https://github.com/encounter/dtk-template)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
