# Nintendo DS ARM7 C/C++ recovery

Generated DS projects now discover ARM7 functions, compile them for ARM7TDMI,
resolve calls and data at their runtime addresses, and link finished source
units into the complete ROM. ARM and Thumb code work with C and genuine C++.
ARM9 keeps its separate ARM946E build settings.

Recognized SDK startup parameters map copied ARM7 blocks to their destination
addresses, including instruction RAM, Thumb startup references, BSS-only blocks
and empty descriptor lists. The header entry is followed when it lies beyond
the initial loader window. Loader bytes, descriptor tables, gaps,
unclaimed data and unfinished functions remain from the owner's input. Module
identities include the CPU and actual overlay ID; overlapping overlay addresses
are not merged into one global address space. Discovery follows entry points,
direct calls and resolved constant BX destinations. Indirect dispatch and unusual
startup code can leave functions undiscovered; discovery is not complete program
recovery.

Use the normal browser or agent workflow to claim a function, obtain a draft,
compile and diff it, and link its file. `edit_file` adds shared declarations,
structs, globals and C++ helpers. `read_data` can inspect an ARM7 data symbol
before assigning it, or a qualified runtime address such as `arm7:autoload0@0x037F9000`;
ambiguous overlay addresses require a module qualifier. `configure_arm7_unit` assigns original data/BSS
ranges and selects C or C++ without allowing code bounds to change. For example:

```text
configure_arm7_unit(path="src/auto/arm7_main_02380040.c",
                   data=".data:0x023800A0:4:arm7_data_023800A0", language="c++")
```

Use addresses from your analysis, not these example addresses. Ranges must fit
the recorded initialized module or BSS and must not overlap another source
unit. Configuration changes preserve existing code matches and the complete
ROM check, or roll back. The file must match its newly assigned data before
linking again. Plain recovered functions need their original unmangled names
in C++, for example `extern "C" int recovered(int)`; classes and templates can
retain C++ linkage.

A function match requires every linked code byte, size, endianness and instruction
mode to match. Branch destinations and literal addresses are checked even when
objdiff reports equivalent instructions. Linking additionally checks every owned
initialized section, BSS extent and runtime address, then consumes the compiled
ELF bytes and compares the complete rebuilt ROM. Changed source cannot be hidden
by copying reference bytes over it. Active source edits must keep this check
passing. Standalone exports include the same build scripts and use native ARM
GNU binutils, CodeWarrior and, outside Windows, wibo. Setup installs these tools;
manual dependencies are in the [README download table](../README.md#downloads-you-install-yourself).

## BIOS-free inspection and isolated checks

Compilation does not require a console BIOS. Encrypted secure-area processing
uses the owner's ARM7 BIOS key table. An image already decrypted for an emulator
can be imported explicitly as **Already decrypted for an emulator**, or with
`tools/ds_pilot.py --input-format decrypted`. That workflow preserves supplied
secure bytes and retained checksum metadata without a BIOS. Automatic mode still
rejects failed decryption. ARM9 BIOS and firmware are emulator runtime inputs.

The separate read-only module inspector and isolated leaf checker remain useful
without importing ARM9:

```sh
uv run python tools/ds_arm7.py /path/to/owned.nds inspect
uv run python tools/ds_arm7.py /path/to/owned.nds draft --module arm7 --address 0x02380000 --size 8 --mode arm --symbol recovered > /path/to/private/recovered.c
uv run python tools/ds_arm7.py /path/to/owned.nds verify --module arm7 --address 0x02380000 --size 8 --mode arm --symbol recovered --source /path/to/private/recovered.c
```

This isolated checker accepts bounded leaves ending in BX LR, rejects unresolved
relocations and has no full-ROM claim. Use the generated project workflow for
calls, globals and complete source units. Keep retail source outside this checkout.

## Protected code and layouts

The pinned ds-decomp/ds-rom importer decodes and re-encrypts supported DS Protect
formats. Qualification includes an original protected-overlay vector and the
retail YV5P ARM9 main's four version 1.00 ranges. Protected overlay ranges
not assigned to discovered functions retain their encryption metadata only when
the linked plaintext is still exact at the original addresses. The separate inspector recognizes
21 bootstrap signatures; a signature is a candidate, not proof of decryption or
authentication. Generated projects create a decoded ARM7 analysis context
for protected ARM7 main programs, copied blocks and overlays through the pinned
toolkit's codecs at each module's runtime address. Every decoded module must
re-encrypt exactly before discovery. Cipher metadata and decoded reference views
stay under ignored `extract/`; completed source objects are checked against those
views, re-encrypted and placed back into the original stored module. Clean exports
regenerate these views. Original version 1.00 fixtures exercise real C/C++ links
in all three ARM7 module types; other protection versions still need individual
qualification. Encoded pointer pools remain in their stored representation.
If a module cannot decode and re-encrypt exactly, its manifest records retention
and discovery makes no source claims for it; complete-ROM verification still applies.

Inspection bounds FAT entries and backward-LZ expansion and preserves constructor,
BSS and signed flags. Signed overlays can be retained in exact rebuilds; the
inspector does not verify their authentication. ARM9 overlays with absent
constructor tables or zero-length tables work with nonzero tail words and BSS
boundaries aligned to four bytes. The original unowned tail word is emitted by
the linker and excluded from recovered-source coverage. Temporary analyzer padding
is removed before target generation; original constructor fields, BSS addresses
and all ROM bytes must still match. Module checks and clean standalone exports
cover these layouts. DSi containers remain a separate implementation.

See the [YV5P retail test record](ds-retail-yv5p.md) for exact rebuild and emulator
results. These checks do not certify a physical console or every DS game.
