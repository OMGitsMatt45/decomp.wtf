# Future work: Game Boy and Game Boy Color: finish mapper and shared layouts

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

Experimental RGBDS assembly workflow exists: browser/CLI import, bank-aware assembly edits, local claims, strict range checks and exact full-ROM exports. No C/C++ recovery is implemented.

## Existing programs to reuse or qualify

RGBDS 1.0.4 already has pinned native Windows/Linux releases. Its C++20 implementation does not make recovered game assembly C++. Existing cartridge reader and decoder are Python.

## Work that remains

- [ ] Add reviewed symbols, data layouts, routine boundaries and hardware-register names.
- [ ] Model mapper state and cross-bank references conservatively, including MBC1 lower windows, indirect bank changes and RAM code.
- [ ] Synchronize layout versions, added entries, splits and symbols in rooms before enabling shared GB/GBC workflows.
- [ ] Treat any future C/C++ recovery as an optional compiler-specific research path, with separate language/runtime and byte-matching criteria.

## Acceptance checks

- [ ] Keep complete opcode oracle, invalid-byte preservation and all current exact export checks on both hosts.
- [ ] Cover multiple mapper families, conflicting bank states, RAM-resident code and shared-layout conflicts.
- [ ] Report assembly and retained base bytes separately; never convert a full rebuild into a recovered-source percentage.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/rom/gb.py`
- `tests/test_gb.py`
- `tests/test_gb_app.py`
- `docs/gameboy-assembly.md`

## References

- [RGBDS](https://github.com/gbdev/rgbds)
- [pokered layout reference](https://github.com/pret/pokered)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
