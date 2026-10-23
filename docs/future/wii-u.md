# Future work: Wii U: qualify PowerPC executable and module matching

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent as a from-scratch platform. GameCube/Wii support does not parse Wii U RPX/RPL modules or establish their compiler compatibility.

## Existing programs to reuse or qualify

Reuse general PowerPC analysis, Ghidra, objdiff and project-build concepts. Evaluate devkitPro homebrew tooling for original fixtures; first prove exact tool/compiler compatibility for each target.

## Work that remains

- [ ] Define a decrypted RPX/RPL loader with compression, imports/exports and relocation handling.
- [ ] Audit endian/ABI, function descriptors and module addressing before adapting drafts.
- [ ] Implement compiler-specific project builds and exact reconstructed module exports; scope disc/container work separately.

## Acceptance checks

- [ ] Cover compressed sections, imports, BSS and cross-module relocations.
- [ ] Compare complete reconstructed modules, retaining unexplained bytes explicitly.
- [ ] Verify native Windows/Linux prerequisites and fail honestly on unavailable matching compiler versions.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/`
- `src/decompnet/rom/`
- `src/decompnet/toolchains.toml`

## References

- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)
- [devkitPro packaging](https://github.com/devkitPro/pacman)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
