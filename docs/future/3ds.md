# Future work: Nintendo 3DS: qualify ARM image and project integration

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Existing project metadata and m2c ARM draft routing recognize 3DS, but there is no from-scratch 3DS importer or proven native matching/export path.

## Existing programs to reuse or qualify

Reuse Ghidra/m2c ARM analysis and evaluate devkitPro tools for original homebrew fixtures. Retail builds require their exact compiler/SDK configuration; devkitARM is not automatically a matching substitute.

## Work that remains

- [ ] Start with user-supplied decrypted executable sections and separate container handling from code matching.
- [ ] Parse code segments, relocations and CRO/CRR modules as explicitly supported formats.
- [ ] Add a project adapter, original compiler selection and exact executable reconstruction before browser import.

## Acceptance checks

- [ ] Verify ARM/Thumb mode, sections, relocations, BSS and module boundaries with original fixtures.
- [ ] Do not download keys or game data; reject unsupported encrypted inputs with a useful explanation.
- [ ] Qualify every build tool on Windows without WSL and Linux, with exact output comparisons.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/catalog.py`
- `src/decompnet/forks/drafts.py`
- `src/decompnet/rom/`

## References

- [devkitPro packaging](https://github.com/devkitPro/pacman)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
