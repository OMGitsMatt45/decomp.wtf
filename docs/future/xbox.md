# Future work: Original Xbox: qualify XBE and compiler-specific project builds

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Xbox is recognized in cached public-project metadata. No from-scratch XBE loader, original-compiler registration or exact export path is implemented.

## Existing programs to reuse or qualify

Evaluate Ghidra x86 analysis, nxdk for original homebrew fixtures and xemu for independent format/debug references. nxdk is a modern open SDK, not a replacement for a retail game's original MSVC compiler.

## Work that remains

- [ ] Parse XBE sections, base addresses, TLS, imports and metadata with private base inputs.
- [ ] Qualify original MSVC versions and exact object/link behavior separately from nxdk fixture builds.
- [ ] Add x86 draft context, object judging and whole-XBE reconstruction with declared metadata handling.

## Acceptance checks

- [ ] Cover relocations, exception/unwind conventions where applicable, imports and TLS initialization.
- [ ] Compare code and data with the selected compiler and verify full XBE output.
- [ ] Verify native Windows and Linux execution requirements without inferring them from an SDK build script.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/catalog.py`
- `src/decompnet/forks/ghidra.py`
- `src/decompnet/rom/`

## References

- [nxdk](https://github.com/XboxDev/nxdk)
- [xemu](https://github.com/xemu-project/xemu)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
