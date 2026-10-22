# Game Boy / Game Boy Color assembly work record

GB/GBC leads the assembly-heavy platform work. The local assembly workbench now
also connects to browser import, the editor and agent claims: inspect an
owner-supplied cartridge, follow direct control flow, review RGBDS sources, and
rebuild the complete cartridge with an exact byte comparison. Assembly projects
use their own judging path and do not enter C/C++ compilation or m2c.

## Use it

```sh
decompnet toolchain install rgbds
decompnet gb inspect "my game.gbc"
decompnet gb export "my game.gbc" "assembly project" --entry 01:4000 --entry 02:4000
python "assembly project/build.py" "my game.gbc"
```

Entries and ranges use hexadecimal bank and CPU addresses. `01:4000` and
`02:4000` refer to different stored bytes. Entry `00:0100` is always included
unless `--no-discover` is supplied. Additional known code can be specified as
`--range 03:4000:4020`, with an exclusive end; ranges cannot overlap each other
or discovered instructions. To use a reviewed layout alone:

```sh
decompnet gb export game.gb reviewed --no-discover --range 00:0100:0104 --range 01:4000:4020
```

An export directory must be empty. The command refuses to overwrite previously
edited sources. It does not copy the original ROM into the export. To rebuild on
a machine without decompnet installed, use Python 3.12+ and the pinned RGBDS
executables: `python build.py game.gb --rgbds /path/to/rgbds-1.0.4`.
The build script itself uses only Python's standard library.

## Browser and agent workflow

Install RGBDS in **Compilers & tools**, or with the command above. Drop a `.gb`
or `.gbc` into the app and use the existing ownership confirmation. The browser
checks the header before import; the server independently checks it again.
Agents use `project_info`, `claim_function(count=1)`, `get_context`, and
`compile_and_diff` with **one complete RGBDS section**, including the exact
exported label shown in the brief. The editor starts with generated assembly
labelled for review. Guides and built-in agent prompts use SM83 instructions.

`context.inc` contains shared numeric constants, e.g. `DEF VALUE EQU $22`.
It is included automatically, and edits are rejected when they break a saved
match. Known external project labels are linked at their recorded banks and CPU
addresses, including `BANK(label)`. Submissions cannot include files or use
INCBIN, EQUS, macros, interpolation or escapes. Section names must be plain
quoted ASCII names. An extra nonempty section, wrong bank/address, wrong size,
missing label, unresolved symbol or differing operand prevents a match.

`split_function(function="...", at="02:4000", new_name="...")` adds a known
entry in a switched bank. An address inside an unverified range splits it only
at an instruction boundary. Generated claim ranges are at most 2048 bytes, so
large stretches fit the submission limit. Bank/CPU addresses display separately
from ROM offsets; the internal unique key is `(bank << 16) | CPU` and is never
used as an instruction operand.

Progress counts **verified assembly bytes over all cartridge bytes**. The app
also reports disassembled range bytes and bytes retained in the base ROM. Even
when every discovered range verifies, unknown code/data remains. C/m2c autopilot
and automatic twin verification are disabled for these projects.

App exports rejudge every saved match, retain annotations and context, compile
verified ranges as separate units, then compare the entire ROM. Invalid saved
matches fall back to regenerated baseline assembly with an explicit report.
Exports go into fresh `source`, `source-2`, etc. directories so edits to previous
exports are preserved. The original ROM remains an explicit build input.

## What runs and what it is

| Component | Implementation / language | Native Windows without WSL | Linux x86-64 |
| --- | --- | --- | --- |
| RGBDS 1.0.4 `rgbasm` / `rgblink` | Upstream C++20 programs; consume SM83 assembly | Upstream Win64 binaries | Upstream x86-64 binaries |
| Cartridge inspection and disassembly | Python | Yes | Yes |
| Browser importer, editor and local agent claims | Python and browser JavaScript; RGBDS for assembly/linking | Yes | Yes |
| Export builder | Python standard library, invoking RGBDS directly | Yes | Yes |
| Game sources in this workflow | SM83 assembly (`.asm`), not C/C++ recovery | Assembled by RGBDS | Assembled by RGBDS |

The registry uses versioned upstream release URLs with SHA-256 pins for both
archives. RGBDS is MIT licensed. No assembler port or compiler build is required.
Its [v1.0.4 CMake configuration](https://github.com/gbdev/rgbds/blob/v1.0.4/CMakeLists.txt)
specifies C++20 for the host programs. This says nothing about a game's original
language. Some games on these platforms use C; this slice recovers assembly and
does not claim to reconstruct the original source.

## Implemented checks and boundaries

- The reader verifies the Nintendo logo, header checksum and declared ROM size;
  it reports the global checksum separately. A nonstandard global checksum is
  preserved, not repaired. GB and CGB flags, MBC type and special 72/80/96-bank
  size codes are recorded. Storage-bank addresses support up to 512 banks.
- The decoder covers the documented base and CB instruction sets, relative
  branches, signed immediates and RGBDS operands. Illegal opcodes, truncated
  instructions and nonzero STOP padding are retained as explicit bytes.
- Discovery follows direct jumps/calls and fallthrough, leaves invalid bytes and
  cartridge headers alone, reports overlapping paths and indirect jumps, and
  stops at absolute writes to mapper control addresses. A ROM0 reference to
  `$4000` never guesses a switched bank. Extra entries select known storage banks.
- Exports give every code range and every retained gap a fixed bank and address.
  Unknown code/data and header bytes come from `INCBIN` of the owner's supplied
  base. Size assertions guard edits. The builder checks the base SHA-256, uses
  exactly RGBDS 1.0.4, and compares the whole linked output before publishing it.
  It never runs `rgbfix`, masks operands or accepts a partial match.
- `assembly_bytes` counts disassembled ranges; `base_bytes` counts retained
  bytes. A successful full rebuild that includes base bytes is not a completed
  disassembly or C/C++ decompilation. There is no recovered-source percentage.

Static discovery does not emulate mapper state. It cannot track bank changes
through registers, bank changes made by a callee, MBC1's switched lower window,
interrupt handler installation, jump tables, code copied to RAM or runtime
decompression. Discovered ranges need review. The bank addresses describe ROM
storage, not a claim that every bank is reachable under every mapper mode.

## Validation

`tests/test_gb.py` checks header rejection, storage-bank identity, conservative
discovery, explicit ranges and the local CLI. RGBDS acts as an independent
encoding oracle for every base opcode, all 256 CB opcodes, all STOP padding bytes,
and signed immediate/branch edge cases. Original synthetic cartridge fixtures
exercise GB/GBC, distinct code at the same CPU address in different banks, a
72-bank image, bad global checksums, relative PC wrap, paths containing spaces,
and standalone exports with no Python packages available.

Required integration cases reject changed source bytes, changed section size,
wrong bank placement and a mismatched base ROM. Native Windows CI checks PE
executables and rebuilds with System32-only PATH; Linux rebuilds with empty PATH.
The dedicated workflow fails rather than skips when RGBDS is missing.

[Native verification run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39522570824):
both Ubuntu 24.04 and Windows Server 2022 passed installation and the required
assembly checks. The broader local regression selection passed 96 tests; five
cases for other installed compiler combinations were skipped. All Game Boy
checks ran, including the standalone builder with only standard-library Python.

`tests/test_gb_app.py` additionally exercises browser upload/try/export endpoints,
single claims and credits, native assembly diffs, banked external symbols,
shared-context regression checks, renames, instruction-boundary splits, added
entries, assembly-specific agent prompts, browser/server header parity, and clean
standalone rebuilds containing the saved annotated assembly. Rejection cases
include an extra one-byte section, a wrong bank/address/operand, wrong extent,
an undefined symbol, invalid assembly, and prohibited file directives.

[Browser/agent native verification run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39524849758):
both Windows Server 2022 and Ubuntu 24.04 passed the expanded checks, including
saved assembly sources, shared constants, explicit bank entries and browser
upload/try/export. Windows assembly and rebuild cases use System32-only PATH.
The focused local regression suite passed 138 checks. A further 17 core C
coordination tests passed with sandboxing disabled for that test process because
this managed container cannot create bubblewrap user namespaces. Broader legacy
compiler integration is also limited locally by unavailable 32-bit execution;
the dedicated Windows/Linux GB/GBC workflow runs all required assembly cases.

```sh
decompnet toolchain install rgbds
python -m pytest -q tests/test_gb.py tests/test_gb_app.py tests/test_toolchains.py
```

## Remaining work, in order

1. Reviewed symbol/data layouts, routine boundaries, mapper-aware cross-bank
   references, hardware register names and handling of RAM-resident code.
2. GB/GBC room-sharing layout synchronization and broader mapper/game coverage;
   this pass validates agents and the editor on one local coordinator.
3. NES/SNES assembly workflows, with separately pinned native toolchains, CPU
   decoders, layouts and exact rebuild tests. Neither is implemented by the
   Game Boy decoder or enabled in the browser importer. The platform roadmap
   covers Nintendo, Xbox and PlayStation consoles. See the
   [future-work index](future-work.md) for the platform plans and remaining
   GB/GBC work.
