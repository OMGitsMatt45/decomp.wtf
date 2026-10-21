# Future work: NES and Famicom: add a mapper-aware assembly workbench

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent: there is no NES importer, CPU decoder, mapper model, assembler integration or verified export.

## Existing programs to reuse or qualify

Evaluate cc65 da65/ca65/ld65 and Mesen debug facilities. Existing projects can inform layouts. Pin and test actual native Windows/Linux release assets before registering them; a 6502 C compiler does not recover original assembly.

## Work that remains

- [ ] Parse iNES/NES 2.0 headers, PRG/CHR layout, trainers and mapper/submapper identity without rewriting metadata.
- [ ] Build a conservative 6502 discovery adapter with bank state, vectors, illegal opcodes and data boundaries.
- [ ] Integrate assembly attempts, bank-aware symbols and lossless exports, starting with a bounded mapper subset.

## Acceptance checks

- [ ] Begin with NROM and one switched-bank mapper, original fixtures and nonstandard header preservation.
- [ ] Reject wrong bank, overflow, relative branch and unsupported mapper cases clearly.
- [ ] Assemble and compare the entire cartridge on Windows and Linux; report retained bytes separately.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/`
- `src/decompnet/toolchains.toml`
- `src/decompnet/app/engine.py`

## References

- [cc65](https://github.com/cc65/cc65)
- [Mesen](https://github.com/SourMesen/Mesen2)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
