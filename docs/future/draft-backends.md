# Future work: Decompiler engines: strengthen m2c/Ghidra and qualify alternatives

Status: **draft work plan; implementation is not complete**. Baseline: v0.19.0.

This PR adds a reviewable work plan. It does not add platform or compiler support.
Keep it in draft while implementation and the checks below remain unfinished.

## Current coverage

m2c is the integrated first-draft backend for supported MIPS/PowerPC/ARM paths; Ghidra is optional for broader architectures. splat/spimdisasm, luvdis, dtk, dsd and RGBDS provide analysis/assembly roles, not interchangeable source decompilers.

## Existing programs to reuse or qualify

Reuse the existing m2c and headless Ghidra adapters. Evaluate RetDec, Reko and radare2/rizin ecosystem decompiler plugins as optional alternatives only after confirming current upstream maintenance, licenses, supported CPUs and native releases. These are candidates, not installed backends.

## Work that remains

- [ ] Define a backend capability contract: architecture/ABI, source language, symbol/data context, timeout, diagnostics and deterministic cache keys.
- [ ] Improve m2c/Ghidra C++ and module context while retaining compiler-specific judging as the authority.
- [ ] Run a small original multi-architecture corpus through candidate engines and document draft usefulness, native packaging and failure behavior before choosing an adapter.
- [ ] Keep static recompilers, disassemblers, assemblers and emulators labeled by their actual role. No backend adds a platform importer or matching compiler by itself.

## Acceptance checks

- [ ] Exercise headless Windows/Linux runs, versioned cache invalidation, cancelled/failed jobs and paths containing spaces.
- [ ] Require candidates to pass compile-and-match through the game compiler; draft output alone is never a match.
- [ ] Ensure optional backend absence preserves existing workflows and does not silently switch compiler or language.
- [ ] Add browser/CLI, claim, failure-reporting and standalone export coverage for any newly enabled workflow.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/seeds.py`
- `src/decompnet/forks/drafts.py`
- `src/decompnet/forks/ghidra.py`
- `src/decompnet/toolchains.toml`

## References

- [m2c](https://github.com/matt-kempster/m2c)
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra)
- [RetDec](https://github.com/avast/retdec)
- [Reko](https://github.com/uxmal/reko)
- [radare2](https://github.com/radareorg/radare2)
- [rizin](https://github.com/rizinorg/rizin)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in the work-plan branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
