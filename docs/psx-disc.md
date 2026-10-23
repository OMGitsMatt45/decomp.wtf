# PlayStation disc reconstruction

PS1 projects export matching complete disc images, with independently rebuilt
boot code and imported overlays. Matching C/C++ replaces assembly function by
function. A byte-identical disc does not establish complete code discovery or
runtime behavior. See [C/C++ matching](psx-cpp.md).

## Console and browser

```sh
decompnet psx inspect "my disc.cue"
decompnet --db "work/app.db" psx import "my disc.cue" --workspace "work/projects" --own-copy --toolchain gcc-2.7.2-psx
decompnet --db "work/app.db" psx recover PROJECT_SLUG --workspace "work/projects" --limit 200
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

Source edits preserve program file sizes. ISO, raw BIN and CUE builds retain
track names, pregaps, audio and subcode. Changed Mode 1 or Mode 2 Form 1 raw sectors receive regenerated EDC and
P/Q error correction. A changed sector with nonstandard original EDC/ECC is
refused for mastering/protection review. Raw unrelocated archive fragments can
change within their original storage. Reviewed zlib/gzip/HBD-LZSS modules can recompress
within declared archive capacity and update a declared stored-length field.
Existing loader fixup words are restored to their original unrelocated storage.
Reviewed additive R_MIPS_32/R_MIPS_26 bases also permit changed values at those
existing sites. New relocation tables still need a loader adapter.

The [resource and recovery guide](psx-resources.md) covers file replacement,
reviewed file/track growth, Heartbeat HBD members, loader scalar fields and bulk
C/C++ recovery. Use `psx upgrade PATH` to refresh copied helpers in older exports
while retaining edited sources and helper backups. Configure each child of a
combined project, then build all discs with the root command.

CHD v5 mod builds use the same commands. The writer preserves every decoded
2448-byte frame outside changed data sectors, including stereo audio, subcode,
track padding and all track/pregap metadata. It restores omitted sector parity,
decodes CD FLAC without replacing samples, recompresses with standard zlib and
updates map CRCs, hunk CRCs and raw/metadata SHA-1 hashes. Every output frame is
read back and compared before publication. Combined builds verify logical
geometry and decoded hashes while allowing the compressed container size to
change. Explicit resource growth can also extend a supported first data track,
update its metadata and retime validated interleaved audio Q, including catalogue
and ISRC timestamps. P/R-W bits and audio stay unchanged. Unknown/protected
subcode requires mastering review. Compression can produce a larger CHD than the original. No additional
tool or download is required. Existing matching builds retain the exact original
compressed container.

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
hash and decoded program bytes. Supported v5 codecs are `cdlz`, `cdzl`, `cdfl`,
`lzma` and `zlib`, plus uncompressed maps and self references. FLAC samples and
subcode decode losslessly; hunk/map CRCs and checksummed metadata are validated.
Parent/delta images and unknown codecs require conversion to a supported
standalone image. Missing tracks are not synthesized.

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
decompnet --db "work/app.db" psx profile PROJECT FUNCTION --small-data 0 --assembler maspsx-2.56 --workspace "work/projects"
```

`--reset` restores the project default. Compiler changes that invalidate saved
matches fail. The API also accepts a bounded flags list. The export records and
reuses each function's settings. A raw module with unknown GP/BSS needs a
reviewed layout; the app cannot infer arbitrary runtime loader state.
`--assembler gnu` selects the compiler's ordinary GNU assembler path. A selected
maspsx profile installs the pinned translator and binutils automatically.

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
exact decoded byte count. `raw`, `zlib`, `gzip` and `hbd-lzss` codecs are supported.
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
the result again to verify it. If capacity is exhausted or an unreviewed loader
relocation word changes, no output is published. Optional additive bases for
R_MIPS_32/R_MIPS_26 allow reviewed inverse authoring at existing sites; see the
[resource guide](psx-resources.md#reviewed-additive-loader-fixups).
Matching builds retain original encoded
storage exactly, regardless of the reserve or storage declaration.

## Standalone builds and qualification

`build.json` pins original hashes, file extents, decoded module hashes and
analysis offsets. `python build.py` regenerates analysis/assembly/assets from
the owner's retained original, compiles recovered C/C++, links each exclusive
module and verifies every analysis byte. Ordinary raw images receive the rebuilt
program bytes at their original extents. CUE/CHD and reviewed encoded modules
retain original containers only after decoded-program matching succeeds.
The separate `mod` command supports bounded source and resource changes,
including reviewed file relocation and first-data-track growth. ISO directory
records, raw parity, CUE indices and supported CHD metadata are verified before
outputs are published. Unknown mastering and loader formats require adapters.

All **231 required checks passed with zero skips on native Windows and Linux**
at source/test commit `93e89e870b8401d0afcdca8ccb2b0552af1368f4` in the
[qualification run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39999362412). Windows/Linux compatibility,
PS2, Game Boy, N64 and DS qualification/execution also passed. The
[validation record](psx-validation.json) pins jobs, counts and private results.
The [required workflow](../.github/workflows/psx.yml) fails on skipped required
suites. Retail bytes and derived sources never enter CI or Git.

All six supplied retail discs pass refreshed complete-image builds and clean
rebuilds: DQVII has **428 matching C/C++ functions per disc** and
**425 shared source files**; Syphon Filter 1 has **189**, Syphon Filter 2 has
**197 per disc** with **195 shared files**, and Syphon Filter 3 has **193**.
Both refreshed combined ZIPs pass every member's CRC check and retain the
original full-disc hashes. Earlier qualified exports remain preserved privately.

Full recovery passes, argument-position fixes, compiler-profile refinement and
verified source reuse increased exact matches from **417 to 1,632** across those
discs. **13,315 recognized entries still remain assembly**; complete disc
reconstruction does not establish full retail source recovery or gameplay.
The console saves genuine C/C++, respects claims and retains unsuccessful
candidates for further work. Recovered address aliases survive standalone
export and clean rebuilding.

Both DQVII HBD archives parse 3,729 blocks and 24,716 members each; all 5,342
standard compressed members were independently decoded. The six formerly
guarded type 1 members per disc are raw GPU uploads. Isolated execution of the
original loader constructor verifies their packed rectangles; fixed-size edits
pass independent parity checks and leave all other sectors identical.
Playthrough and disc-swap validation remain with the user.

```sh
uv sync --locked --group dev
uv run --no-sync python -m tools.operational --psx-only
DECOMP_TEST_PSX_CPP=1 uv run --no-sync python tools/run_operational.py tests/test_psx.py tests/test_psx_cpp.py tests/test_psx_disc.py tests/test_psx_workflows.py tests/test_psx_set.py tests/test_psx_media.py tests/test_psx_layout.py tests/test_psx_modify.py tests/test_psx_growth.py tests/test_psx_storage.py tests/test_psx_chd.py tests/test_psx_assets.py tests/test_psx_hbd.py tests/test_psx_subcode.py tests/test_psx_recover.py tests/test_psx_relocation_authoring.py tests/test_overlays.py "tests/test_export.py::test_export_rebuilds_the_game[psx]"
uv run --no-sync python tools/check_operational_results.py --psx-only operational-results.xml
```

In PowerShell set `$env:DECOMP_TEST_PSX_CPP = '1'` first and omit the shell
prefix. No additional PSY-Q or Sony ASPSX version is qualified by this work.

The dev dependency group installs pycdlib for independent ISO reads and Unicorn for original-fixture
MIPS execution checks. Those checks exercise larger bodies, helper calls,
initialized globals, new zero storage and function pointers; they do not
establish whole-game execution or playthrough correctness.

The original CHD fixtures were generated and independently verified/extracted
with MAME chdman 0.276. Their [provenance](../tests/fixtures/psx-chd/provenance.json)
pins every input hash; the generator uses original code, PCM and subcode only.
Local `chdman verify` and `extractraw` also verified modified output from all
five codecs, including both SHA-1 hashes and every decoded frame. Native tests
use these fixtures directly and require no external CHD executable.
An additional grown CHD passed MAME verification and BIN/TOC extraction with
retained audio, subcode and virtual pregap. Native resource tests cover that
geometry change and combined C++/resource edits on ISO, CUE and CHD projects.
