# PlayStation disc and overlay reconstruction

Status: **implemented and qualified on native Windows and Linux**: 60 required
checks per host, zero skips. The [validation record](../psx-validation.json)
pins the tested source revision and native jobs.

PR #4 implements complete-image matching for eligible ISO 9660 PS1 discs,
including independently rebuilt boot programs and discovered raw/PS-X EXE
overlays. See the [disc guide](../psx-disc.md) for supported sector layouts,
console commands, reconstruction boundaries and the native qualification.

## Implemented

- Filesystem inventory and pinned program extents, with explicit header versus
  inferred absolute-call address evidence.
- Complete ISO, 2352-byte Mode 1/Mode 2 Form 1 and 2448-byte-frame matching
  exports preserving opaque metadata, unrelated files, trailers and audio.
- Independent linking and strict C++ recovery for mutually exclusive overlays;
  original fixtures exercise separate targets and claims at shared addresses.
- Regeneration from the owner's original disc in clean exported trees, paths
  containing spaces, corrupted-target/source rejection and stale-output removal.
- Browser/CLI coverage and required native Windows/Linux qualification for the
  existing original PS1 GCC 2.7.2 and 2.8.1 C/C++ compiler paths.

## Remaining scope

Retail disc coverage and loader review remain separate validation work. Raw
overlay placement is heuristic; a matching disc hash does not prove every
code file or runtime address was discovered. Runtime-relocated overlays,
compressed/archive code, multi-extent/interleaved ISO files, CUE authoring,
absent tracks and CHD recompression need additional adapters and fixtures.

No additional PSY-Q compiler or ASPSX version is registered. Compatible GNU
assembly is not proof of equivalence to every original Sony assembler.
Additional versions require source/license/checksum provenance and native
Windows/Linux instruction, constant-data and relocation parity separately.
The pinned compiler ports, compatible binutils, maspsx, splat and m2c remain
the tools to reuse; current compiler hosts need no replacement.

No commercial ROMs, SDK payloads, BIOS files or keys belong in this branch.
See the [main roadmap](../future-work.md).
