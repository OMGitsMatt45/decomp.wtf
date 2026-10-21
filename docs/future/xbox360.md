# Future work: Xbox 360: qualify Xenon code and XEX reconstruction

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Xbox 360 appears in public-project metadata and the compiler pack contains related MSVC tools. Neither fact establishes a raw-game importer or verified Xbox 360 matching/export support.

## Existing programs to reuse or qualify

Audit the existing compiler pack and licensing, Ghidra PowerPC analysis, objdiff and Xenia format/debug references. Do not infer matching from the presence of a compiler executable.

## Work that remains

- [ ] Start with decrypted XEX/PE module layouts and document compression, imports, relocations and metadata.
- [ ] Model Xenon PowerPC ABI, VMX128 instructions and compiler-specific code generation.
- [ ] Qualify a working compiler/linker invocation and project adapter before from-scratch import.

## Acceptance checks

- [ ] Verify ordinary PowerPC and VMX128 cases, imports, relocation tables and whole-module reconstruction.
- [ ] Record compiler version, flags and licensing; test native Windows and actual Linux hosting separately.
- [ ] Use original fixtures and keep unsupported signed/encrypted container work out of matching claims.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/catalog.py`
- `src/decompnet/toolchains.toml`
- `src/decompnet/forks/ghidra.py`

## References

- [Xenia research reference](https://github.com/xenia-project/xenia)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
