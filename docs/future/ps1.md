# PlayStation disc and overlay reconstruction

Status: **implemented in PR #4 and qualified on native Windows/Linux: 498 required checks per host, zero skips**.
The [validation record](../psx-validation.json) pins tested revisions, native
jobs and private retail results. See the [disc guide](../psx-disc.md) for commands.

## Implemented

- Complete ISO, raw 2352/2448-frame matching and pinned filesystem extents.
- One multi-disc source project, shared verified C/C++, one build command,
  independent disc hashes and one private downloadable ZIP.
- CUE pregaps, relative track sets and opaque audio retention; CHD container
  retention after decoded-program verification, including corrected v5 raw maps.
- Module GP/BSS from EXE headers and explicit reviewed loader facts, with
  separate links/targets for modules sharing RAM; per-function GCC profiles.
- Reviewed raw/zlib/gzip archive fragments and explicit MIPS relocations,
  preserving original encoded storage after strict decoded matching.
- Binary EXE header preservation, wider boot-text recovery and stable function
  discovery. Private DQVII two-disc testing exercises these retail fixes.
- Browser/CLI workflows, clean standalone builds, changed-source/original
  rejection and removal of stale combined outputs.
- Separate fixed-slot C/C++ mod builds for standalone and combined projects,
  module-specific linking and regenerated raw-sector EDC/ECC. Original function
  addresses and program file sizes stay fixed; strict matching builds remain available.
- Syphon Filter 1/2/3 private retail testing: all four discs rebuild exactly and
  from clean sources, including one combined SF2 project/ZIP. Embedded non-R3000
  words and four-byte function alignment have regression coverage.
- Larger C/C++ bodies, helpers and owned data in reviewed loaded zero reserves,
  retaining original entry addresses and function-pointer identity. Original
  MIPS fixtures execute the generated bodies and pointer-return helpers.
- Reviewed zlib/gzip module recompression, explicit archive stored-length fields,
  bounded encoded capacity and preservation of original loader fixup words.
- Lossless CHD v5 mod builds, including FLAC stereo audio, raw subcode, omitted
  parity restoration, retained metadata and independently checked CRC/SHA-1.
  Combined builds allow changed compression sizes with fixed logical tracks.
- Resource extraction/replacement, reviewed file relocation and first-data-track
  growth, ISO extent/volume updates, CUE audio-index shifts and supported CHD
  track growth. Independent pycdlib reads and MAME verification supplement tests.
- Heartbeat HBD inventories, raw/LZSS member extraction and bounded repacking.
  Both DQVII discs pass a complete standard-member census and independent decode;
  real member edits preserve other sectors and independently verify EDC/ECC.
- Reviewed scalar loader LBA/size/sector fields and additive R_MIPS_32/R_MIPS_26
  inverse authoring at existing sites, including HBD-LZSS code fragments.
- Agent-free console C/C++ recovery, optional installed compiler-profile search,
  claim handling, interruption reports and resumption. Full private passes and
  refinement increased exact function matches from 417 to 1,632 across six
  discs; unresolved functions retain assembly.
- Export helper upgrades with backups, preserving edited sources and assets.
  Commands and limits are in the [resource guide](../psx-resources.md).
- Fixed-size raw GPU upload edits for all six previously guarded HBD members on
  each supplied DQVII disc, with loader-constructor execution and sector parity
  checks. Unknown type/geometry combinations remain guarded.
- Standard audio Q position/catalogue/ISRC retiming during CHD data-track growth,
  preserving other subchannels, audio and stored/virtual pregaps and postgaps.
  MAME verifies/extracts all three original timing fixtures.
- Memory-load/store recovery templates, explicit zero-filled assembly fragments,
  reduced draft overhead and preserved unused MIPS argument slots in inferred
  integer/pointer signatures. Reviewed and wider signatures stay intact.
- Automatic address aliases referenced by verified C/C++ survive standalone
  export even when the original assembly did not name them. Refreshed source
  projects pass clean complete-disc rebuilding; both combined ZIPs pass CRCs.
- Period maspsx 2.56/2.86 profiles, G0/G8 searches and standalone profile
  retention; module GP-aware drafts, inferred call-slot and narrow-argument
  alternatives pass the same strict compiler/link judge. Improved saved source
  candidates remain eligible for profile searches.
- Scoped local overlay jump labels survive import and draft generation.
  Concurrent per-function compiler updates preserve other workers' profiles.
- Reviewed raw module copies share canonical source targets and update together
  in mod builds, with original identity checks and retained archive padding.
- Architectural GP state wrappers support explicit original-GCC register
  bindings. Reviewed console split/merge operations preserve evidence and
  reject stale compilation results. Failed drafts remain available for repair.
- Bounded MIPS control-flow summaries preserve forwarded argument registers
  through known call chains. Literal BIOS tail-dispatch candidates are labeled
  architectural GNU C, require an explicit C compiler profile and pass the full
  judge; an equivalent zero-selector encoding still fails exact matching.

## Validation boundaries

A disc round-trip does not prove full source recovery or runtime correctness.
Private retail inputs broaden coverage; they do not qualify every game's loader.
Raw overlay placement still needs review. Proprietary archives/codecs and
unknown relocation tables need specific loader facts/adapters; interleaved or
multi-extent ISO layouts, missing tracks and new loader
relocation tables remain outside this workflow. Nonstandard/protected subcode
and unknown mastering require specific adapters. Source growth
requires explicit loaded-space review; zero bytes alone do not establish nonuse.
HBD block growth cannot change absolute block positions. Most recognized
executable functions remain assembly while source recovery continues.

No additional PSY-Q compiler or ASPSX version is registered. The pinned compiler
ports, binutils, maspsx, splat and m2c remain the tools to reuse. BIOS/firmware is
unnecessary for this decompilation/reconstruction workflow. Playthrough and
disc-swap validation remain with the user.

No commercial ROMs, game-derived source/assembly, SDK payloads, BIOS files or
keys belong in this branch. See the [main roadmap](../future-work.md).

Reviewed boot-data envelopes and differing-call-site signature repairs passed native qualification at a5b1297.

Experimental [PS1 PC source output](../ps1-native.md) is implemented, including
the source-shipped hardware runtime and one build for an ordered disc set.
The execution model remains hybrid while compiled coverage is expanded for
disc-loaded programs, copied routines and runtime patches. The [integration
record](ps1-native.md) describes the CPU and full-runtime qualification scope.
Exhaustive retail source matching remains checkpointed in PR #26.
