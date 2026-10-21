# Future work: PlayStation: broaden disc and overlay reconstruction

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Implemented C/C++ matching and exports using original PS1 GCC 2.7.2 and 2.8.1 on both hosts. Native GCC 2.8.1 and constant-data parity work supersedes old PR #2.

## Existing programs to reuse or qualify

Reuse both pinned PS1 compiler ports, compatible MIPS binutils, maspsx, splat and m2c. Current compiler hosts need no replacement.

## Work that remains

- [ ] Inventory disc filesystem, overlay load addresses and relocation conventions across reviewed fixtures.
- [ ] Design an explicit full-disc rebuild path beyond the existing program payload export.
- [ ] Qualify additional PSY-Q compiler/assembler versions separately; never label compatible assembly as proven equivalence to every original assembler.

## Acceptance checks

- [ ] Keep compiler-version-specific code, constant-data and relocation parity on native Windows and Linux.
- [ ] Round-trip a multi-overlay original fixture and preserve disc metadata or report unsupported fields.
- [ ] Reject wrong addresses, changed globals and corrupted targets; rebuild exported projects in paths containing spaces.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/psx.py`
- `src/decompnet/rom/overlays.py`
- `docs/psx-cpp.md`

## References

- [maspsx](https://github.com/mkst/maspsx)
- [old-gcc](https://github.com/decompals/old-gcc)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
