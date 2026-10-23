# Future work: PlayStation 3: qualify PPU and SPU as separate targets

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent: no PS3 loader or matching pipeline exists. Existing PowerPC support does not implement Cell PPU ABI, SPU code or PS3 containers.

## Existing programs to reuse or qualify

Use Ghidra and RPCS3 format/debug information as research references. Compiler, assembler and linker availability must be established per PPU/SPU target; no matching native compiler bundle is claimed.

## Work that remains

- [ ] Separate decrypted PPU ELF/PRX, SPU ELF/local-store code and signed containers in the format model.
- [ ] Implement PPU function descriptors/TOC and SPU overlays, DMA references and local-store address spaces independently.
- [ ] Qualify original compiler outputs and runtime conventions before offering C/C++ matching.

## Acceptance checks

- [ ] Test PPU TOC relocations, cross-module calls and SPU instruction/local-store edge cases.
- [ ] Build original fixtures with documented compiler provenance and compare complete modules.
- [ ] Require Windows/Linux build evidence; keep unsupported SPU or container features visibly unavailable.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/`
- `src/decompnet/forks/`
- `src/decompnet/toolchains.toml`

## References

- [RPCS3 research reference](https://github.com/RPCS3/rpcs3)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
