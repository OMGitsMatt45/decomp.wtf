# PS1 resources and console recovery

These commands supplement [complete-disc and multi-disc builds](psx-disc.md).
Normal `python build.py` still verifies an exact reconstruction. Resource edits
are applied only by `python build.py mod`, after the original assembly baseline
passes. BIOS and firmware files are unnecessary.

## Update an existing export

After updating decomp.wtf, refresh the copied helpers in older source projects:

```sh
decompnet psx upgrade "/path/to/source-project"
```

This works at a single-disc or combined root. It keeps edited sources and asset
declarations, and backs up each replaced helper as
`NAME.before-upgrade-SHA256`. New exports already include current helpers.

## Replace a disc file

Extract to a path outside the exported project, edit that copy, then stage it:

```sh
decompnet psx extract "source-project" --file DATA/CONTENT.BIN --output "editing/content.bin"
decompnet psx replace "source-project" --file DATA/CONTENT.BIN --input "editing/content.bin"
decompnet psx build "source-project" --mod
```

The command writes a private copy under `mod-assets/` and records it in
`psx-assets.json`, bound to the original disc's SHA-256. Subsequent edits to that
staged file are read by the next mod build. Mapped programs must be changed
through their source; a resource replacement cannot overwrite them.

Smaller files and growth within the original sector allocation keep their LBA.
For larger files, first review whether the game uses ISO directory lookup or
has additional absolute-address tables, then stage with `--relocate`:

```sh
decompnet psx replace "source-project" --file DATA/CONTENT.BIN --input "editing/content.bin" --relocate
```

Growth appends the replacement to the first data track, leaving every other
file's LBA fixed. The original allocation remains in place. The build updates
the file's ISO extent and byte length in both byte orders, plus volume bounds.
It regenerates raw-sector addresses and EDC/ECC. This does not infer or rewrite
undocumented game address tables.

Known loader scalar fields can be supplied through `--references refs.json`:

```json
[
  {"file": "LOOKUP.BIN", "offset": 0, "kind": "lba", "width": 4, "endian": "little"},
  {"file": "LOOKUP.BIN", "offset": 4, "kind": "size", "width": 4, "endian": "big"},
  {"file": "LOOKUP.BIN", "offset": 8, "kind": "sectors", "width": 4, "endian": "little"}
]
```

Offsets are bytes within the named original ISO file. Widths 2, 3 and 4 are
supported. Each field must initially equal the original resource's LBA, byte
size or rounded-up sector count. Overflow, overlapping fields, source edits to
those bytes, and references inside another replaced resource are refused.

CUE growth preserves data/audio pregaps, shifts audio INDEX values in a shared
BIN and retains the audio bytes. Separate audio files remain unchanged. CHD v5
growth supports ordered CHT2 metadata with a first MODE1_RAW/MODE2_RAW track and
optional audio tracks. It updates the first track length, keeps four-frame
alignment and retains other metadata and audio. Ordinary interleaved audio Q
packets are validated against track metadata and retimed, including position,
catalogue and ISRC packets. Audio samples and every P/R-W bit stay unchanged.
Stored/virtual audio pregaps and postgaps retain their timing; CHD alignment
padding is excluded from CD time. Invalid CRCs, inconsistent positions, unknown
packet/encoding forms and protected mastering remain guarded. Nonzero Q with a
leading data-track pregap needs a dedicated layout review. Original
CHD track padding must be zero before it can become ordinary data sectors.
Nonstandard EDC/ECC also requires mastering review. Fixed-geometry CHD edits
continue to retain audio and subcode verbatim.

Whole-file replacements are bounded to 128 MiB each, archive members to 16 MiB,
all staged data to 256 MiB and declarations to 4,096 entries. In a combined
project, configure each `discs/disc-N` child, then run the root build once.
Results record changed files, archive blocks, loader fields and output hashes.
Failure on any disc clears all combined mod outputs.

## Heartbeat HBD archives

Inventory and extract directly from an original disc; replacement targets an
exported disc directory:

```sh
decompnet psx archive inspect "game.cue" --file HBD1PS1D.W71
decompnet psx archive extract "game.cue" --file HBD1PS1D.W71 --sector 1 --member 0 --output "editing/member.bin"
decompnet psx archive replace "source-project" --file HBD1PS1D.W71 --sector 1 --member 0 --input "editing/member.bin"
decompnet psx build "source-project" --mod
```

`--sector` counts 2,048-byte sectors from the start of the archive; `--member`
is zero-based within that block. `inspect --full` includes every member record.
The scanner validates block/member bounds and reports gaps as opaque sectors.
It accepts disc tags 0 and 1; the supplied US DQVII discs use one of each.

Raw members and the standard `0x500` LZSS form support decoded extraction and
replacement. The decoder handles a zero-filled 4,096-byte ring, bounded output
and zero alignment/terminators. Raw allocation hints larger than stored bytes
are retained without inventing missing data; edits to those members must keep
the original stored length. Type 1 GPU uploads also support raw extraction and
fixed-size replacement. Their header packs x/y/width into the destination word
and height into its top bits plus the low byte at +12. That byte is not always
a compression flag: `0x46` and `0x20` are heights on the supplied DQVII members.
The parser checks the VRAM rectangle and exact byte count; authoring keeps the
rectangle and header intact. All six formerly guarded members per supplied
DQVII disc now pass these checks. Other unknown layouts stay guarded;
`extract --stored` retrieves their original bytes for investigation.

Repacking retains all other members, flags, types, unknown words, disc tags and
absolute block positions. It can consume verified zero padding within a block's
original sector allocation. Exhausting that allocation or removing a whole
sector is refused: changing external block-address tables needs loader facts.
An archive containing a mapped program cannot also receive resource edits.

Reviewed code fragments may use `codec: "hbd-lzss"` in an import layout. Their
load address, GP, BSS, decoded size, code range, storage capacity and loader
length fields still require review; archive membership does not establish code.

## Reviewed additive loader fixups

Existing `R_MIPS_32` and `R_MIPS_26` relocation declarations can include a `base`
when the loader adds that known base to the stored address or jump target:

```json
{"offset": 8, "type": "R_MIPS_32", "value": "0x80180500", "base": "0x80180000"}
```

Import first verifies that the original stored addend plus base equals `value`.
Mod builds can then inverse-transform changed values, preserving jump opcodes
and checking range/alignment. Records without a base retain their original
fixup words. This does not discover or add relocation sites, rewrite unknown
loader tables or provide additive HI16/LO16 authoring.

## Recover C/C++ without an AI agent

```sh
decompnet --db "work/app.db" psx recover PROJECT --workspace "work/projects" --limit 200 --max-insns 24
decompnet --db "work/app.db" psx recover PROJECT --workspace "work/projects" --limit 200 --search-profiles
```

Recovery tries deterministic integer/memory-leaf source candidates and m2c drafts,
then accepts only exact compiler and full-link matches. It uses the project's
C/C++ language and original PS1 compiler settings. `--leaves-only` omits m2c;
`--search-profiles` also probes installed GCC 2.7.2/2.8.1 C/C++ frontends at O0/O1/O2, G0/G8,
and installed GNU/maspsx 2.56/2.86 assembler profiles. It retains saved improved
sources while trying these alternatives and saves
compiler settings only after an exact match. Failed probes keep existing
settings. No inline-assembly replacement is saved as recovered C/C++.
Standalone exports retain automatic address aliases referenced by verified
C/C++ objects, including aliases absent from the disassembler's symbol list.

Omit `--limit` and `--max-insns` for a full pass through remaining functions.
The templates model aligned loads, stores and preserved load-before-store
values. Zero-filled entries are reported as `assembly_fragments` and retained
as assembly; they do not consume the attempt limit or become invented C stubs.
Console recovery generates one m2c draft per attempt rather than a second
browser preview draft. Inferred integer/pointer signatures retain unused MIPS
argument words, so a third argument stays in its original register even when
earlier arguments are unused. Wider or reviewed signatures are left intact.
The original failed draft remains available for diagnosis; repeating the same
compile failure in the same context keeps one failure record. Profile searches
can retry that source with the installed frontends without granting recovery
credit for a failed compile.
A full pass is a set of verified candidates, not a claim
that every binary function has been recovered.

Progress goes to stderr and the final JSON reports accepted functions, failed
attempts, profile changes and remaining work. Reruns skip matched functions;
Ctrl+C returns a partial report. Existing claims are respected. Stop browser
autopilot before using this command on the same local project. Unresolved
functions remain assembly; exact bytes do not establish source-level intent or
whole-game behavior.

## Review a function boundary

An inferred boundary may split one routine or combine independently called
routines. Review the original control flow and entry references before using:

```sh
decompnet --db "work/app.db" psx split PROJECT FUNCTION --at 0x80012340 --workspace "work/projects"
decompnet --db "work/app.db" psx merge PROJECT HEAD TAIL --reason "Reviewed shared stack frame and epilogue; no external tail entries" --workspace "work/projects"
```

Merges require adjacent open ranges in one module, original byte agreement and
no outside code/data references into the tail. The review archives both old
ranges, sources, attempts and profiles before replacing the active boundary.
It grants no recovered credit. New source must pass the ordinary full judge;
stale work against earlier boundaries is rejected.

## Format references and validation

Primary Heartbeat format research:

- [DQIV_PSX_TOOLS format notes](https://github.com/RadMageIRL/DQIV_PSX_TOOLS/blob/main/FORMAT.md)
- [DQ4 block definitions](https://github.com/mwilkens/dq4psxtrans/blob/91fcfcb264188f565f31058e51b01b656aebe667/libs/blockDefs.py)
- [Heartbeat block reader](https://github.com/mschroeder-github/dragon-hackst-4/blob/567c02b6d86d1632efc7247cb46f193cace5202e/dragon-hackst-4/src/main/java/net/markus/projects/dh4/HBD1PS1D.java)

The private DQVII validation compared all 5,342 standard compressed members per
disc against the independent DQIV_PSX_TOOLS decoder, then checked actual member
edits on both discs with independent sector parity tests. The six raw GPU
uploads on each disc additionally pass isolated execution of the original
retail header constructor, with its allocator stubbed, reproducing the expected
rectangles and zero encoding byte. All twelve upload edits preserve unrelated
sectors and pass independent parity checks. Those checks qualify
the measured storage format, not all Heartbeat games or runtime semantics.
Original fixtures additionally use pycdlib to read resized ISO files and MAME
chdman to verify/extract grown CHDs. The [validation record](psx-validation.json)
distinguishes native regression tests, private structural checks and prior
complete retail builds. No retail bytes or derived source are published.

Q packet layouts and CRC behavior follow the
[PSX-SPX subchannel specification](https://github.com/psx-spx/psx-spx.github.io/blob/master/docs/cdromformat.md#cdrom-subchannels).
The CD timeline follows
[MAME's CHD track/pregap mapping](https://github.com/mamedev/mame/blob/master/src/lib/util/cdrom.cpp).
MAME also independently verifies/extracts authored fixtures containing retimed
position, catalogue and ISRC packets with stored/virtual pregaps and postgaps.
