# YV5P retail test record

The owner supplied a decrypted 128 MiB DS image: YV5P, revision 0, Dragon Quest V
Europe. SHA-256: `15ac0888fbcda0fcfef0623ddbb47630ed8d8bb5968d2f2e563c3d9243362be7`.
Archive parts, ROM, BIOS/firmware, extracted data, screenshots and recovered
retail source remain outside Git. This record contains metadata and results only.

## Reconstruction and recovery

- Explicit decrypted import rebuilds **all 134,217,728 bytes exactly without a
  BIOS**. The input retains a pre-processing secure-area checksum and has a
  noncanonical prefix. The importer preserves both as supplied; it does not
  decrypt the bytes again or exempt any header/code ranges from comparison.
- The normal project indexes 12,357 ARM9/ITCM/overlay functions and 260 ARM7
  functions. ARM7 SDK parameters identify a 488-byte loader and copied blocks
  at `0x037F8000` (68,652 initialized bytes) and `0x027E0000` (98,128 bytes).
  Recovery and linking use those runtime addresses, not their file-loading
  coordinates.
- A bounded 32-function ARM7 draft pass produces 12 exact matches. All 12 source
  units, totaling **148 bytes**, enter the complete ROM rebuild through compiled
  and linked ELF bytes. The rebuilt image still matches every supplied byte.
  Nonmatching and unsupported drafts are retained as failures, not recovered code.
- An earlier isolated leaf experiment independently verified 20 of 29 candidates,
  totaling 552 bytes, at their corrected runtime addresses. This is separate from
  the 12 source-linked units; do not add the two byte counts as new coverage.
- All 44 ARM9 overlays are compressed and signed. Independent bounded BLZ decoding
  matches all 44 toolkit outputs. Signed metadata and stored bytes survive the
  exact rebuild; the read-only inspector does not authenticate signatures.
- ARM9 main contains DS Protect **1.00**, with four protected instruction ranges.
  The pinned importer decodes these ranges and re-encrypts them in the exact ROM
  rebuild. The limited standalone scan of ARM7/overlays does not inspect ARM9 main.

The earlier automatic-mode control attempted to decrypt this already-decrypted
input and changed exactly 12 bytes: `0x6C–0x6D`, `0x15E–0x15F`, and
`0x4000–0x4007`. Its failed-decryption guard remains in place. The owner confirmed
the input format; selecting that format resolves the supplied image's rebuild
failure. The failed control remains a failed control.

## Emulator execution

Original and ARM7-source-linked images run in separate fresh melonDS libretro
processes, pinned to commit `66b5d2634cd0a79030562811e6e05f5532f800ba`, with the
interpreter and software rendering. The owner's BIOS7, BIOS9 and firmware are
private runtime inputs; they are not used by the decrypted rebuild.

A 1,200-frame no-input run reaches the title animation. A 3,600-frame scripted
joypad run passes the title/menu flow and reaches the opening throne-room scene.
Original and rebuilt images have identical video and audio observations at all
four checkpoints in each run. RAM hashes are recorded separately because the
core's RTC can differ between fresh processes. Screenshots were inspected
privately. This validates the observed boot/menu/opening sequence, not a complete
playthrough or physical-console operation.

Reproduce a private trace from a checkout with:

```sh
uv run python -m tools.ds_trace --core /path/to/melonds_libretro.so --bios-dir /path/to/private/runtime --frames 3600 --inputs /path/to/private/joypad.json --output /path/to/private/trace /path/to/original.nds /path/to/rebuilt.nds
```

Use a `.dll` core on Windows. The input JSON contains zero-based frame intervals,
for example `[{"start":1200,"end":1204,"buttons":["a"]}]`. The tool writes a report,
private core logs and checkpoint screenshots. It reports observations, not
fixture-specific CPU counters or automatic gameplay completion.
