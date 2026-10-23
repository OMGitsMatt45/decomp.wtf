# Future work: Nintendo Switch: qualify AArch64 module and build adapters

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Switch can appear in cached public-project metadata and general AArch64 drafts, but there is no from-scratch Switch importer or verified matching compiler pipeline.

## Existing programs to reuse or qualify

Reuse Ghidra AArch64 analysis, objdiff and project integration; evaluate devkitPro tooling for original fixtures. Existing tools do not supply original retail compiler flags or a complete rebuild.

## Work that remains

- [ ] Start with decrypted NSO/NRO or ELF inputs, section compression, relocations and module metadata.
- [ ] Add reviewed AArch64 ABI/draft context and exact compiler/build provenance.
- [ ] Treat Switch 2 as a separate deferred qualification target; do not infer compatible formats or compiler behavior from the first Switch.

## Acceptance checks

- [ ] Check compressed segments, dynamic relocations, imports, BSS and complete module bytes.
- [ ] Exercise original homebrew fixtures on both hosts and reject unsupported container/encryption formats.
- [ ] Verify matches with the selected original toolchain; distinguish analysis-only projects from rebuildable projects.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/catalog.py`
- `src/decompnet/forks/ghidra.py`
- `src/decompnet/app/guide/aarch64.md`

## References

- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)
- [devkitPro packaging](https://github.com/devkitPro/pacman)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
