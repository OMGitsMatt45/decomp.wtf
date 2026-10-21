# Future work: Modern consoles: record PS4/PS5 and Xbox One/Series feasibility gates

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Absent and deferred: PS4, PS5, Xbox One and Xbox Series have no integrated importer, exact compiler setup or verified export. Shared x86-64 architecture is insufficient evidence of support.

## Existing programs to reuse or qualify

General Ghidra analysis and existing project-build integration may be reusable for authorized decrypted executables. No ready matching toolchain, signing workflow or complete console reconstruction is promised.

## Work that remains

- [ ] Document each console separately: accessible executable format, ABI/extensions, relocations, compiler provenance, legal original fixture and native tool availability.
- [ ] Begin with existing lawful homebrew/research projects and project-mode analysis rather than unsupported retail container import.
- [ ] Require a separate scoped implementation proposal after the evidence gates pass; keep Switch 2 qualification with the Switch work plan.

## Acceptance checks

- [ ] Demonstrate a reproducible original fixture with code/data/relocation comparison before changing platform status.
- [ ] Record unsupported encrypted/signed containers without downloading keys or pretending a desktop compiler matches retail code.
- [ ] Qualify native Windows/Linux tools and identify any actual porting requirement per target.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/`
- `src/decompnet/forks/`
- `docs/future-work.md`

## References

- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)
- [objdiff](https://github.com/encounter/objdiff)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
