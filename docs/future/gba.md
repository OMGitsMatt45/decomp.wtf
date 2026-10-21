# Future work: Game Boy Advance: integrate the distinct ARM compiler path

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Normal and old agbcc Thumb C/C++ backends are implemented and verified on native Windows and Linux. The separate 2.9-arm-000512 compiler is not an integrated application variant.

## Existing programs to reuse or qualify

Reuse installed Thumb compilers, Arm GNU preprocessing/assembly, luvdis and m2c. Upstream supplies a Linux ARM C executable; native Windows ARM hosting and an ARM C++ frontend require separate qualification and likely porting.

## Work that remains

- [ ] Add explicit ARM-mode compiler identity and variant selection without routing it through either Thumb backend.
- [ ] Qualify a native Windows host of that exact ARM compiler and its corresponding frontend sources before promising C++.
- [ ] Handle ARM/Thumb transitions, literal pools and branch veneers in analysis, matching and exported layouts.

## Acceptance checks

- [ ] Compare ARM-mode code/data/relocations against the exact original compiler on Linux and Windows.
- [ ] Cover interworking, halfword-aligned Thumb functions and invalid variant selection.
- [ ] Keep both existing Thumb C++ pipelines and byte-identical clean ROM exports passing.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/gba.py`
- `src/decompnet/project.py`
- `tools/gba_cpp/`
- `docs/gba-cpp.md`

## References

- [agbcc](https://github.com/pret/agbcc)
- [luvdis](https://github.com/aarant/luvdis)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
