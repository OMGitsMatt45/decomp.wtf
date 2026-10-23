# PlayStation disc and overlay reconstruction

Status: **implemented in PR #4 and qualified on native Windows/Linux: 125 required checks per host, zero skips**.
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
  addresses, file sizes and data stay fixed; strict matching builds remain available.
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

## Validation boundaries

A disc round-trip does not prove full source recovery or runtime correctness.
Private retail inputs broaden coverage; they do not qualify every game's loader.
Raw overlay placement still needs review. Proprietary archives/codecs and
unknown relocation tables need specific loader facts/adapters; interleaved or
multi-extent ISO layouts, missing tracks, changed-size files/tracks, new loader
relocation tables remain outside this workflow. Growth
requires explicit loaded-space review; zero bytes alone do not establish nonuse.
DQVII's HBD archives remain
opaque, and most recognized executable functions remain assembly.

No additional PSY-Q compiler or ASPSX version is registered. The pinned compiler
ports, binutils, maspsx, splat and m2c remain the tools to reuse. BIOS/firmware is
unnecessary for this decompilation/reconstruction workflow. Playthrough and
disc-swap validation remain with the user.

No commercial ROMs, game-derived source/assembly, SDK payloads, BIOS files or
keys belong in this branch. See the [main roadmap](../future-work.md).
