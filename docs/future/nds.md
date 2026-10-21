# Future work: Nintendo DS: resolve encrypted imports and reconstruction gaps

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Generated ds-decomp projects and CodeWarrior C/C++ matching are implemented. Existing draft PR #1 contains distinct encrypted-import, unit-layout and ARM/Thumb fixes absent from main; it must be preserved and reviewed.

## Existing programs to reuse or qualify

Reuse pinned dsd, native Windows CodeWarrior tools, wibo on Linux, objdiff and m2c. Rebase and review PR #1 rather than replace it with a tracking document.

## Work that remains

- [ ] Finish PR #1 review: private user-supplied ARM7 BIOS handling, overlapping entry points, word-aligned units, unused sections and function-local instruction mode.
- [ ] Resolve the reported secure-prefix/checksum rebuild differences without masking bytes or weakening the whole-ROM comparison.
- [ ] Expand ARM7, ARM9, autoload and overlay coverage, including runtime-loaded modules and compiler-version differences.

## Acceptance checks

- [ ] Rebase PR #1 and rerun its focused tests plus current native Windows/Linux DS operational suites.
- [ ] Use legal original encrypted/unencrypted fixtures and confirm any BIOS stays in ignored private paths.
- [ ] Verify module checks, symbol addresses, restored ARM/Thumb mode and a strict full-ROM rebuild; retain failures as failures.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/scratch_dsd.py`
- `src/decompnet/forks/ds_template/`
- `src/decompnet/forks/drafts.py`
- `tests/test_ds.py`

## References

- [Existing unfinished PR #1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1)
- [ds-decomp](https://github.com/AetiasHax/ds-decomp)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
