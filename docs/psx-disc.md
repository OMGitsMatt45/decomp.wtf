# PlayStation disc reconstruction

PS1 projects export matching complete disc images, with independently rebuilt
boot code and imported overlays. Matching C/C++ replaces assembly function by
function. A byte-identical disc does not establish complete code discovery or
runtime behavior. See [C/C++ matching](psx-cpp.md).

## Console and browser

```sh
decompnet psx inspect "my disc.cue"
decompnet --db "work/app.db" psx import "my disc.cue" --workspace "work/projects" --own-copy --toolchain gcc-2.7.2-psx
decompnet --db "work/app.db" psx export PROJECT_SLUG --workspace "work/projects"
decompnet psx build "work/projects/PROJECT_SLUG/source"
```

Create the database's parent directory first. `inspect` needs no compiler and
reports filesystem records, module addresses, address evidence and matching
eligibility. Imports retain private copies of the disc and referenced tracks.
The original GCC 2.7.2/2.8.1, binutils, splat, maspsx and m2c dependencies install
automatically. BIOS/firmware is unnecessary for decompilation and reconstruction.

In the browser, drop an ISO/BIN/CHD, confirm ownership, and export from **Source**.
For CUE sets use **file on this computer** and enter the CUE path: all referenced
track files must be accessible to the local application. A CUE uploaded alone
cannot supply its companion tracks. A reviewed layout can be selected before
import. Existing program-only projects need reimporting to retain full media.

## One project for multiple discs

Import the discs into the same workspace, then group their slugs in disc order:

```sh
decompnet --db "work/app.db" psx combine DISC_1_SLUG DISC_2_SLUG --title "My game" --workspace "work/projects"
decompnet --db "work/app.db" psx export DISC_1_SLUG --workspace "work/projects"
```

The browser has the same disc-order controls under **Source**. Exporting any
member produces one `source-set/` project and one private `source-set.zip`,
containing the sources, pinned original inputs, and verified disc outputs.
The browser can download that ZIP. Keep it private: it contains game bytes.

Run `python build.py` at the combined root to build every disc. Identical
recovered source text is shared under `shared/src/`; every use compiles against
its own disc's context, compiler, addresses, GP and target bytes. Disc-specific
source/assets remain under `discs/disc-N/`. The root `objdiff.json` covers all
discs. Each original image retains its own identity and database targets.
Different discs with the same executable cannot collapse into one import.

Outputs are listed in `disc-set.json`. Each must match its own complete input
hash, and a failed build clears all combined outputs. CUE references and track
filenames remain together. These are the separate discs used for normal emulator
disc swapping. Disc-change gameplay still needs playthrough validation.
`psx ungroup PROJECT --workspace PATH` restores independent exports.

## Modified C/C++ builds

Edit sources in an exported project, then run:

```sh
python build.py mod
# Or from another directory:
decompnet psx build "/path/to/exported/project" --mod
```

The build first reconstructs the original assembly baseline exactly. Without a
reserve declaration, changed C/C++ must fit its original function size and cannot
add owned data, BSS or helpers. Existing functions and globals remain available
at their pinned addresses. Normal `python build.py` continues to require exact
matching of the recovered sources.

For larger functions, review a range that is unused and loaded by the original
module, then record it with the console. These addresses are examples:

```sh
decompnet psx reserve "/path/to/exported/project" --module main --start 0x80010600 --size 0x200
decompnet psx build "/path/to/exported/project" --mod
```

`psx-mod-space.json` binds the declaration to the original analysis hash. The
range must contain only original zeros, be aligned and inside the loaded file,
and avoid original functions, loader fixups and BSS initialization. A zero range
alone is not proof that the game leaves it unused; that is a loader-review fact.
Larger bodies, helpers, constants, initialized globals and new zero-initialized
storage link into the reserve. Entry jumps retain the original function
addresses, including function-pointer identity. Existing callers and other
original data stay fixed. Exhausting the reserve fails and clears mod outputs.
Interior references and ambiguous section-relative addresses require review;
new runtime constructors and unsupported relocations are refused.

For a combined game, run `reserve` in each `discs/disc-N` directory before the
root mod build. Each disc retains its own hash-bound declaration and compiler
context, including when the source is shared.

Single-disc results are under `build/psx-mod/`, with hashes and changed-function
records in `build/psx-mod-result.json`. At a combined root, one command builds
every disc under `build/mod/`; `build/mod/disc-set-result.json` records each
output. Shared source changes compile independently for every disc. Any failed
disc removes the combined mod outputs.

ISO, raw BIN and CUE builds preserve file sizes, track names, pregaps, audio and
subcode. Changed Mode 1 or Mode 2 Form 1 raw sectors receive regenerated EDC and
P/Q error correction. A changed sector with nonstandard original EDC/ECC is
refused for mastering/protection review. Raw unrelocated archive fragments can
change within their original storage. Reviewed zlib/gzip modules can recompress
within declared archive capacity and update a declared stored-length field.
Existing loader fixup words are restored to their original unrelocated storage
and must remain unchanged in the decoded module. Rewriting relocation tables
and CHD recompression require separate adapters. This workflow does not resize
files or recover unknown loaders and archives.

## Supported media

| Input | Matching workflow |
| --- | --- |
| ISO 9660, 2048-byte sectors | Complete image reconstruction |
| Raw 2352-byte Mode 1 / Mode 2 Form 1 | Complete image reconstruction |
| Raw 2448-byte frames | Complete image, including opaque subcode |
| CUE with one first data track and optional audio | Validated relative BINARY tracks and indices; original track set retained after program verification |
| Standalone CHD v5 with supported codecs | Original compressed container retained after decoded-program verification |
| Standalone PS-X EXE | Executable payload only |
| Interleaved, multi-extent, multi-volume or extended-attribute ISO | Complete reconstruction refused with a reason |

CUE matching supports data pregaps and audio in the same or separate files.
Missing tracks, escaping paths, inconsistent modes/indices and unsupported
statements fail explicitly. CHD matching checks both the original compressed
hash and decoded program bytes; audio remains opaque. It does not re-encode
CHD, synthesize missing tracks, or author changed media. Existing CD FLAC
analysis does not decode audio samples. All original audio bytes remain in the
retained container.

Unrelated files, sector envelopes, XA metadata, padding, trailers, subcode and
audio stay verbatim. Ordinary mapped programs require Mode 1/Mode 2 Form 1 data
sectors. Damaged/ambiguous directories, partial sectors and cyclic trees fail
or report boot-program-only recovery.

## Module addresses, GP/BSS and compiler choices

`SYSTEM.CNF` supplies the boot path, including nested directories. PS-X EXE
headers supply load addresses and BSS ranges; module-specific GP values are
kept separate. Raw overlay addresses remain inferred from absolute calls and
must be reviewed against the loader. Mutually exclusive modules retain separate
functions, targets, claims and links even at identical RAM addresses.

If the initial text guess excludes the boot entry, entry/control-flow and MIPS
frame evidence recover a wider text envelope. Import repeats discovery with
function hints until stable, so export does not silently introduce recovery
targets absent from the project. These heuristics do not establish that every
code block was recognized.

Individual functions can use different qualified compiler profiles:

```sh
decompnet --db "work/app.db" psx profile PROJECT FUNCTION --toolchain gcc-2.8.1-psx --language c++ --optimization O2 --workspace "work/projects"
```

`--reset` restores the project default. Compiler changes that invalidate saved
matches fail. The API also accepts a bounded flags list. The export records and
reuses each function's settings. A raw module with unknown GP/BSS needs a
reviewed layout; the app cannot infer arbitrary runtime loader state.

## Reviewed archive, compression and relocation layouts

Use `psx import ... --layout reviewed.json` to supply known loader facts for
modules that automatic discovery cannot identify. This replaces the discovered
non-boot overlay list with the declared modules. The JSON is bound to the
original disc SHA-256 reported by `inspect`:

```json
{
  "format": 1,
  "sha256": "ORIGINAL_DISC_SHA256",
  "modules": [{
    "name": "battle", "path": "CODE.ARC", "offset": "0x100",
    "stored_size": "0x800", "size": "0x2000", "codec": "zlib",
    "load": "0x80180000", "code_start": 0, "code_end": "0x1800",
    "gp": "0x80188000", "bss": "0x80182000", "bss_size": "0x100",
    "storage": {"capacity": "0x1000", "length_offset": "0x20",
                "length_width": 4, "endian": "little"},
    "relocations": [{"offset": 8, "type": "R_MIPS_26", "value": "0x80180500"}]
  }]
}
```

`offset`/`stored_size` select a bounded fragment of an ISO file; `size` is the
exact decoded byte count. `raw`, `zlib` and `gzip` codecs are supported.
`load` addresses the first decoded byte; text offsets select the code inside it.
GP/BSS and relocations default to zero/empty. Relocation records give explicit
resolved values for `R_MIPS_32`, `R_MIPS_26`, `R_MIPS_HI16` and `R_MIPS_LO16`.
Offsets, opcodes, bounds, duplicate records and overlapping storage are checked.
The tool applies these reviewed records to the analysis targets and retains
encoded storage only after independently rebuilt targets match exactly.
It does not discover proprietary archives, infer relocation tables or support
unspecified codecs. Loader review remains necessary for those formats.

`storage` is optional and enables modified compressed output. `capacity` covers
the encoded stream and explicitly reviewed unused bytes immediately after it;
extra capacity must originally be zero. `length_offset` is relative to the same
archive file and must point to its actual stored-size field. Two- and four-byte
fields in either byte order are supported. Its original value must equal
`stored_size`; it cannot overlap a module allocation or another length field.
Mod builds recompress, update this field, zero the unused allocation and decode
the result again to verify it. If capacity is exhausted or a loader relocation
word changes, no output is published. Matching builds retain original encoded
storage exactly, regardless of the reserve or storage declaration.

## Standalone builds and qualification

`build.json` pins original hashes, file extents, decoded module hashes and
analysis offsets. `python build.py` regenerates analysis/assembly/assets from
the owner's retained original, compiles recovered C/C++, links each exclusive
module and verifies every analysis byte. Ordinary raw images receive the rebuilt
program bytes at their original extents. CUE/CHD and reviewed encoded modules
retain original containers only after decoded-program matching succeeds.
The separate `mod` command supports the bounded source changes described above.
Changed-size media authoring remains outside this workflow.

All **125 required checks passed with zero skips on native Windows and Linux**
at source/test commit `eaf93c02c3d23c8e291a7382331a6c251cebb409` in the
[qualification run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39917105672).
The [validation record](psx-validation.json) records per-suite counts and private
retail results: both DQVII discs rebuild exactly, with 190 matching C++ functions
and 92 shared source files. Most functions remain assembly and HBD archives stay
opaque. Syphon Filter 1/2/3 adds four exact complete-disc and clean rebuilds,
41 matching C++ functions and a combined SF2 project with eight shared sources.
The public console inspection command verifies each of these inputs. Both
combined retail ZIPs passed every member's CRC check and full-disc hashes.
A real Syphon Filter source edit changed one sector with valid EDC/ECC and all
other sectors identical; gameplay was not tested. The
[required workflow](../.github/workflows/psx.yml) fails on any skipped required
suite. Retail bytes and derived sources never enter that workflow or Git.

```sh
uv sync --locked --group dev
uv run --no-sync python -m tools.operational --psx-only
DECOMP_TEST_PSX_CPP=1 uv run --no-sync python tools/run_operational.py tests/test_psx.py tests/test_psx_cpp.py tests/test_psx_disc.py tests/test_psx_workflows.py tests/test_psx_set.py tests/test_psx_media.py tests/test_psx_layout.py tests/test_psx_modify.py tests/test_psx_growth.py tests/test_psx_storage.py tests/test_overlays.py "tests/test_export.py::test_export_rebuilds_the_game[psx]"
uv run --no-sync python tools/check_operational_results.py --psx-only operational-results.xml
```

In PowerShell set `$env:DECOMP_TEST_PSX_CPP = '1'` first and omit the shell
prefix. No additional PSY-Q or Sony ASPSX version is qualified by this work.

The dev dependency group installs Unicorn automatically for original-fixture
MIPS execution checks. Those checks exercise larger bodies, helper calls,
initialized globals, new zero storage and function pointers; they do not
establish whole-game execution or playthrough correctness.
