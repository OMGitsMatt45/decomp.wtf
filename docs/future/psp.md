# Future work: PSP: add Allegrex-aware executable and module workflows

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Public-project metadata and m2c MIPS draft routing include PSP. Raw PSP import, Allegrex/VFPU analysis and verified export are absent.

## Existing programs to reuse or qualify

Evaluate PSPDEV tools for original fixtures and Ghidra/m2c for analysis. Existing PS1/PS2 toolchains cannot be assumed to emit the correct Allegrex ABI or original compiler output.

## Work that remains

- [ ] Parse decrypted ELF/PRX modules, relocations and imports/exports.
- [ ] Handle Allegrex extensions, VFPU instructions and delay slots without passing unknown instructions through a plain MIPS model.
- [ ] Qualify exact period compiler configurations and create a module reconstruction/export adapter.

## Acceptance checks

- [ ] Test VFPU encodings, relocation types, module stubs and GP-relative data.
- [ ] Use original fixtures and verify complete module bytes on native Windows and Linux.
- [ ] Reject encrypted/unsupported modules explicitly; do not treat a homebrew SDK as universal retail matching support.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/drafts.py`
- `src/decompnet/rom/`
- `src/decompnet/toolchains.toml`

## References

- [PSPDEV](https://github.com/pspdev/pspdev)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
