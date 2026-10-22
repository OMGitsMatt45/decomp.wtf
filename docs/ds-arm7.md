# BIOS-free DS module inspection and initial ARM7 recovery

Decompilation and compilation do not inherently require console BIOS files.
This developer CLI reads ARM7 and overlay modules directly from an ordinary DS
image. An opaque ARM9 secure area does not prevent this work. Whole-project DS
imports still need the ARM7 BIOS key table when decrypting or reproducing the
encrypted secure area. ARM9 BIOS and firmware are emulator runtime inputs.

From a checkout:

```sh
uv run python tools/ds_arm7.py /path/to/owned.nds inspect
uv run python tools/ds_arm7.py /path/to/owned.nds draft --module arm7 --address 0x02380000 --size 8 --mode arm --symbol recovered > /path/to/private/recovered.c
uv run python tools/ds_arm7.py /path/to/owned.nds verify --module arm7 --address 0x02380000 --size 8 --mode arm --symbol recovered --source /path/to/private/recovered.c
```

The addresses above are examples; supply a function's actual start, full size
and ARM/Thumb mode from your analysis. Keep recovered retail source outside the
checkout. Inspection installs no tools and writes no files. Drafting uses the
existing separately installed m2c; verification uses installed CodeWarrior for
DS (`2.0/sp1p5` by default, selectable with `--compiler`). Setup installs those
tools, and the [README download table](../README.md#downloads-you-install-yourself) covers
manual dependencies. Native Windows runs CodeWarrior directly; Linux uses wibo.

Verification accepts C and `--language c++`; C++ definitions need an unmangled
name, for example `extern "C" int recovered()`. It targets ARM7TDMI, compares
the entire function's raw bytes and size, checks the object's instruction mode,
and rejects relocations rather than masking them. A mismatch exits with status
1. Inline assembly and user pragmas are rejected by the existing source checker.

This is initial isolated-function recovery. Drafts currently need a bounded
leaf ending in `bx lr`, without external branches, calls or PC-relative data.
Unsupported operations remain errors. Linking complete ARM7 units into generated
projects, automatic function discovery, browser/agent integration, and functions
that need link context remain open. The normal project builder retains ARM7's
original bytes. A CLI function match does not claim a rebuilt or bootable ROM.

The inspector keys modules by CPU and actual overlay ID, supports out-of-order
IDs and overlapping runtime addresses, and retains BSS/constructor/flag metadata.
It bounds FAT entries and backward-LZ expansion. Signed overlays can be decoded
for inspection, but their authentication is explicitly unverified. Signed ARM7
overlays are excluded from recovery. ARM9 main remains with the existing import
decoder; this CLI does not interpret an encrypted or compressed ARM9 main as code.

DS Protect work begins with the 21 known bootstrap signatures from ds-rom 0.8.0
(MIT; attribution and license accompany the table). Hits identify candidates in
decoded modules and block ARM7 recovery pending decoding/validation. They do not
authenticate a module, prove an exact variant, or implement protected-code
decryption/re-encryption. No hit is not evidence that the whole game is unprotected.

See the [YV5P retail test record](ds-retail-yv5p.md) for measured results and the
remaining secure-area failure.
