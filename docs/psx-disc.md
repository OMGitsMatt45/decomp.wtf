# PlayStation disc reconstruction

PS1 disc projects can export a matching **complete image**, including their
independently rebuilt boot executable and discovered overlays. This extends
the existing [C/C++ matching workflow](psx-cpp.md). PS1 remains beta; the new
disc qualification uses original fixtures rather than retail game images.

Drop an ISO/BIN into the app, confirm ownership, then export from **Source**.
The export reports either **complete disc** or **program payload only**. The
same workflow is available from the console:

```sh
decompnet psx inspect "my disc.bin"
decompnet --db "work/app.db" psx import "my disc.bin" --workspace "work/projects" --own-copy --toolchain gcc-2.7.2-psx
decompnet --db "work/app.db" psx export PROJECT_SLUG --workspace "work/projects"
```

Create the database's parent directory first. `inspect` needs no compiler and
prints JSON with the filesystem inventory, discovered overlay addresses,
address evidence, file extents and full-image reconstruction eligibility.
Imports retain a private copy of eligible discs; different images with an
identical boot executable remain separate projects. Existing program-only
projects need reimporting from their discs to gain reconstruction provenance.

## Games with multiple discs

Import and export **each disc separately**, in the same workspace if desired.
The projects have separate slugs and are identified by the complete disc's
hash, so Disc 1 and Disc 2 cannot collapse into one project even when their
boot executables are identical. Each export retains that disc's unique assets,
overlays, filesystem and sector layout. Keep both rebuilt images and the
original external track descriptions for the emulator's normal disc swap.

Shared source can be reused manually where it matches both versions; each
project verifies it against its own targets. Discs can also have different
executables or compiler settings. The current workflow does not combine discs
into one image, synchronize shared source automatically or validate a game's
disc-change behavior. The original two-disc fixture checks independent
rebuilds of images with identical boot code and different resource contents.

## Supported layouts

| Input | Complete-image matching |
| --- | --- |
| ISO 9660, 2048-byte sectors | Supported |
| Raw 2352-byte Mode 1 / Mode 2 Form 1 data sectors | Supported |
| Raw 2448-byte frames, including 96 subcode bytes | Supported |
| Standalone PS-X EXE | Executable payload only |
| CHD | Import and program recovery; no CHD reconstruction |
| Multiple BIN files and external CUE track layouts | No CUE parsing, track assembly or authoring |
| Interleaved, multi-extent, multi-volume or extended-attribute ISO files | Full-image reconstruction refused with a reason |

Unrelated files, opaque sector envelopes, XA metadata, padding, subcode and
audio bytes in the selected image are preserved verbatim. Every rebuilt
program extent must use ordinary 2048-byte data sectors. Mode 2 Form 2 code
files, overlapping filesystem allocations, duplicate names/versions, damaged
records, truncated sectors and cyclic directories fail validation or explicitly
limit recovery to the boot program. Keep an external CUE sheet separately;
the app does not validate that sheet or reconstruct absent tracks.

## Programs, overlays and address evidence

The boot program comes from `SYSTEM.CNF` (or `PSX.EXE`). Nested boot paths are
retained for extent mapping. Files carrying a PS-X EXE header supply their
load address explicitly. Raw overlays retain the existing absolute-JAL
placement heuristic and any prefix before code; `inspect` labels those
addresses as inferred. Two overlays may share RAM while retaining separate
function names, targets, claims and links.

Inferred placement is evidence to review against the game's loader, not proof
of its runtime address. Relocatable overlays, compressed files, custom archive
members, files with little recognizable code and runtime relocation tables
are not automatically recovered. Their stored bytes stay intact. A complete
disc round-trip establishes reconstruction of the selected image; it does not
establish that every code file was found or decompiled. Additional PSY-Q
compiler/ASPSX versions require their own native code, data and relocation
qualification; this PR registers no additional compiler or assembler version.

## Standalone matching builds

The exported `build.json` records the original disc hash, filesystem records,
program file extents, analysis offsets, program hashes and overlay addresses.
Your original `baserom-disc.iso` or `baserom-disc.bin` stays ignored by Git.
`python build.py` regenerates the joined analysis image from that original,
assembles remaining functions, compiles matched C/C++ and links mutually
exclusive modules independently. It verifies every rebuilt analysis byte,
writes the rebuilt program bytes into their original disc extents in a
streamed copy, then verifies the complete output's size and SHA-256.

The result is `build/disc.iso` or `build/disc.bin`. Executable file trailers,
sector EDC/ECC and other original bytes survive unchanged. This matching path
does not resize files, move extents, author new sectors or recompute error
correction for changed payloads. A changed source, wrong target/address,
corrupted original or mismatching full output fails instead of producing a
qualified disc. A failed standalone build removes its previous disc output.
Clean rebuilds need no generated assembly, assets, objects or analysis image.

## Qualification

The [PS1 native workflow](../.github/workflows/psx.yml) requires both original
GCC 2.7.2/2.8.1 C/C++ paths on Windows Server 2022 and Ubuntu 24.04. Missing
required tools, failed tests and skipped required suites fail qualification.
It includes existing compiler-version code/data/relocation parity, original
multi-overlay discs, claims and reads at shared addresses, wrong-source
rejection, complete ISO/raw-frame exports, clean rebuilds in paths with
spaces, browser import/export errors and console inventory/import/export.

```sh
python -m tools.operational --psx-only
DECOMP_TEST_PSX_CPP=1 python tools/run_operational.py tests/test_psx.py tests/test_psx_cpp.py tests/test_psx_disc.py tests/test_psx_workflows.py tests/test_overlays.py "tests/test_export.py::test_export_rebuilds_the_game[psx]"
python tools/check_operational_results.py --psx-only operational-results.xml
```

On PowerShell, set `$env:DECOMP_TEST_PSX_CPP = '1'` before running the second
command without the shell environment prefix. All game bytes and derived
assembly remain private; only the original fixture generators belong in Git.
