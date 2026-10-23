# Future work: PlayStation Vita: qualify ARM module reconstruction

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent: no Vita loader, platform adapter, compiler registration or verified export is present.

## Existing programs to reuse or qualify

Evaluate VitaSDK and Ghidra ARM/Thumb analysis for original fixtures. VitaSDK installation/build tooling and native Windows availability require qualification; a Unix shell recipe is not proof of a native Windows package.

## Work that remains

- [ ] Start from user-supplied decrypted ELF modules and model relocations, import/export tables and module metadata.
- [ ] Determine compiler versions, ABI and per-function ARM/Thumb modes before draft integration.
- [ ] Implement exact module exports and project-build support before enabling browser import.

## Acceptance checks

- [ ] Use original fixtures covering Thumb-2, literal pools, imported symbols and relocation tables.
- [ ] Prove native Windows operation without WSL or report a required host port/build as unfinished.
- [ ] Check full module output and preserve unknown metadata and private input files.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/`
- `src/decompnet/forks/`
- `src/decompnet/toolchains.toml`

## References

- [VitaSDK package manager](https://github.com/vitasdk/vdpm)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
