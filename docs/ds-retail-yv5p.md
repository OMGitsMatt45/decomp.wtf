# YV5P retail test record

The owner supplied a 128 MiB DS image: YV5P, revision 0, Dragon Quest V Europe.
SHA-256: `15ac0888fbcda0fcfef0623ddbb47630ed8d8bb5968d2f2e563c3d9243362be7`.
Archive parts, ROM, BIOS files, extracted data and recovered retail source remain
outside Git. This record contains metadata and results only.

## Results

- Full project import fails secure-area validation before registering matching
  targets. The supplied 16 KiB BIOS7 matches the standard known BIOS hash.
  An independent KEY1 implementation also fails to produce the expected marker
  or CRC for this input; the same implementation decrypts the original encrypted
  qualification fixture correctly with this BIOS. The retail failure remains
  unresolved. It is not counted as a passing rebuild or attributed conclusively
  to either the dump or the toolkit.
- BIOS-free inspection validates module bounds and decodes ARM7 plus all 44
  ARM9 overlays, all 44 compressed. Signed flags are retained;
  overlay authentication is not verified by this inspector. ARM9 main is excluded
  from this CLI's decoding and protection scan.
- No known DS Protect bootstrap signatures were found in those 45 decoded
  modules. This limited scan cannot establish that the entire game is unprotected.
- A bounded ARM7 pass selected 29 leaf candidates referenced by ARM `bl`
  instructions, using their original disassembly through `bx lr` for the target
  size. m2c drafts were compiled with CodeWarrior DS 2.0/sp1p5 for ARM7TDMI.
  **20 candidates matched all 552 target bytes exactly**, with no relocations.
  Six candidates differed after compilation, and three contained unresolved
  privileged operations. Neither group was counted as recovered.

These are isolated C matches, not complete ARM7 source-unit linking, whole-ROM
reconstruction, retail gameplay validation, or physical-console certification.
The original-fixture rebuild/execution qualification from PR #7 remains separate.
Further work includes secure-area provenance/decoding, linked ARM7 data and calls,
and verified DS Protect decoding/re-encryption.
