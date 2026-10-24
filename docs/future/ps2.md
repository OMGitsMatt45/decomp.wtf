# Future work: PlayStation 2: finish disc exports and qualify additional tooling

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Native Windows EE-GCC 2.96 C/C++ hosts, ordinary pinned installation, strict matching and exact flat-payload / ELF-envelope exports shipped in v0.19.0. The exact conventional GNUPro base source remains missing.

## Existing programs to reuse or qualify

Reuse the verified original-instruction EE hosts, original Linux compiler and pinned binutils. Evaluate PS2Recomp and psretrox as separate analysis/recompilation helpers; ico-pc is a game-specific reference, not a generic matching backend.

## Work that remains

- [ ] Implement disc filesystem and separate overlay repacking with explicit ownership of layout metadata.
- [ ] Continue the exact GNUPro source investigation only against identifiable original releases; EE 2.9 and SN 2.95 are different compilers.
- [ ] Assess the three user-supplied projects for reusable format/runtime knowledge and compatible licenses. Record matching decompilation versus static recompilation separately.

## Acceptance checks

- [ ] Keep original-driver C/C++ code/data/relocation parity and clean managed installs on both hosts.
- [ ] Use an original multi-file fixture to verify ELF segments, overlays and complete rebuilt disc bytes.
- [ ] Keep x87 behavior, pipe/failure propagation and System32-only Windows PATH checks; do not accept a runnable recompile as a byte match.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/ps2.py`
- `tools/ps2_cpp/`
- `docs/ps2-cpp.md`
- `docs/ps2-cpp-source-search.md`

## References

- [PS2Recomp](https://github.com/ran-j/PS2Recomp)
- [psretrox](https://github.com/cualquiercosa327/psretrox)
- [ico-pc](https://github.com/nathanialf/ico-pc)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
