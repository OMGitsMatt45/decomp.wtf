# Future work: SNES and Super Famicom: add 65816 assembly reconstruction

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent: the application has no SNES loader, 65816 state analysis or matching/export pipeline.

## Existing programs to reuse or qualify

Evaluate WLA-DX or ca65/ld65 for assembly and Mesen for independent debugging. Their CPU support is reusable; native package availability and exact assembler syntax still need qualification.

## Work that remains

- [ ] Detect LoROM/HiROM and extended mappings while preserving copier headers and ROM metadata.
- [ ] Track 65816 M/X widths, emulation/native state, data/program banks and direct-page assumptions conservatively.
- [ ] Add SPC700 and enhancement-chip support only as explicitly separate bounded targets, with their own decoders and tools.

## Acceptance checks

- [ ] Use opcode/width oracles, bank-crossing edge cases and original LoROM/HiROM fixtures.
- [ ] Round-trip headers, checksums, gaps and all ROM bytes without silently repairing them.
- [ ] Require native Windows/Linux assembly and export checks before enabling the importer.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/`
- `src/decompnet/toolchains.toml`

## References

- [WLA-DX](https://github.com/vhelin/wla-dx)
- [cc65](https://github.com/cc65/cc65)
- [Mesen](https://github.com/SourMesen/Mesen2)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
