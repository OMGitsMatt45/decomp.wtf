# Supplied ROM validation — 2026-10-21

Seven owner-supplied inputs were imported and exported through the running app's
HTTP API. Each output below compared equal to the original bytes in the stated
scope. The private inputs, generated assembly, project databases and detailed
job records stay outside this repository.

| Input | Import | Exact rebuild scope |
| --- | --- | --- |
| EEPROM & SRAM Erase Program, N64 | 220 functions | Complete 1,179,648-byte cartridge |
| S World 3 Beta 1, GBA | 54 functions | Complete 10,144-byte cartridge |
| PSY-Q Debugging Station Boot Disk, PS1 | 4 functions | Main PS-X EXE; BIN/CUE container is not repacked |
| Super Bender Boot Disc, PS2 | Main program and overlays | Combined flat payload (3,502 exported functions) and reconstructed original main ELF |
| M3DS Real / PASSCARD3, DS | 102 instruction ranges | Complete 262,144-byte cartridge, including both ARM programs and retained data |
| FreeLoader 1.04, GameCube | 4 instruction ranges | Complete 108,532-byte extracted apploader image; disc container is not repacked |
| FreeLoader, Wii | 5 instruction ranges | Complete 112,144-byte extracted apploader image from the Update partition; disc container is not repacked |

This establishes import, analysis, assembly rebuilding and equality in those
scopes. It does not establish emulator/console bootability or recovered C++.
The DS and FreeLoader utilities use explicit GNU assembly workflows. Discovered
instruction bytes are 23,296 (DS), 1,040 (GameCube), and 1,812 (Wii); the remaining
bytes are explicitly retained from the owner's verified base image. Coverage is
separate from reviewed/verified assembly progress. Indirect control flow can
require further analysis.

## Repairs

- PS2 initialized `.lit4`/`.lit8`, `.sbss` placement, BSS alignment gaps and zero
  tails retain their original layout.
- Exclusive overlay symbols are scoped and address lookups select the correct
  program. Programs sharing virtual addresses link separately and are placed at
  their original file offsets, avoiding overlapping-section link failures.
- GBA exports resolve literal labels across assembly pieces during assembly,
  retain the disassembler's initial Thumb mode and need no period compiler when
  no C/C++ source is present. A separately pinned ARM binutils tool provides the
  assembler/linker on Linux without installing the full C compiler toolchain.
- Filesystem-free DS launchers import both ARM9 and ARM7 directly. Apploader-only
  GameCube/Wii utilities import their actual boot program, without inventing a
  main DOL. Wii partition reads decrypt and verify sector data hashes.
- The GNU assembly judge verifies the original function label, address, extent,
  resolved instructions and all allocated output. Typed ARM/Thumb targets avoid
  unintended interworking veneers. App prompts and exports identify these
  projects as assembly and expose the rebuild scope.
- Docker compilation mounts pinned tool/runtime directories read-only, runs
  without networking and keeps the compiler sandbox enabled.

## Validation and limits

Synthetic open test inputs cover overlapping PS2 programs, cross-module BSS,
GBA cross-piece literals, mixed ARM/Thumb DS code, encrypted Wii Update
partitions, changed instructions, missing labels and disallowed file directives.
The relevant regression suite passed 169 tests, with nine optional/compiler
checks skipped and four period-compiler export cases excluded in this cloud.
JavaScript syntax, dependency lock consistency and `git diff --check` passed.

For each of the three boot utility projects, an explicit HTTP API smoke probe
rejected a wrong function label, accepted and linked the correct assembly with
score zero, displayed its diff, and exported an identical rebuild incorporating
that verified range. These three test probes are assembly verification, not
C/C++ recovery or automatic completion of all generated listings. They ran in
Docker with pinned native ARM/PowerPC tools.

A broader run additionally encountered ten existing cloud-runtime failures:
nine host-GCC/network tests could not create bubblewrap user namespaces, and one
legacy KMC test could not execute an i386 compiler on this kernel. No sandbox was
disabled to make the supplied-ROM API workflows pass. Period C/C++ compiler
matching therefore remains unverified in this cloud; the seven successful
rebuilds do not establish a fully green compiler suite. Native Windows execution
was not rerun here.
