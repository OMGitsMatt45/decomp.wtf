# Experimental DS static PC repositories

PR #29 begins the DS execution backend. It translates explicitly reviewed ARM9,
ARM7 and overlay instruction ranges to C++ and generates a standalone source
repository. This is a working original-program milestone. It cannot yet turn a
retail Dragon Quest or Pokémon ROM into a playable PC port.

This page describes the small CPU-comparison backend (`nds-generate`). The
additional [DS hardware-runtime adapter](nds-native-runtime.md), `nds-native`,
analyzes ROMs automatically and ships a pinned native runtime. Its original
hardware fixture exercises both screens, sound, IRQs, IPC and cartridge saves.
Retail compatibility is tracked separately.

## Generate and build

The development installation needs Python 3.12+ and `uv sync --locked --group dev`.
Given an original input and its reviewed profile:

```sh
uv run decomp pc nds-generate original.nds reviewed.json output --experimental
uv run decomp pc verify output
cd output
python tools/extract_assets.py /path/to/original.nds
cmake -S . -B build
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

The generated repository builds independently of decomp.wtf. Its prerequisites
are Python 3.9+ for extraction, CMake 3.20+ and a C++17 compiler. Use Visual Studio
2022's Desktop development with C++ workload on Windows, or GCC/Clang on Linux.
Manual download links are in the [README](../README.md#downloads-you-install-yourself).
There are no external runtime libraries, BIOS files or console compiler inputs
for this generated fixture path.

Run `build/ds_static --assets assets` on Linux or
`build/Release/ds_static.exe --assets assets` with Visual Studio. The runner prints
actual CPU registers, NZCV flags, reviewed memory words and overlay loads as JSON.
`--max-steps N` sets a positive instruction budget. `--save saves/game.sav`
persists the profile's RAM checkpoint; create the parent directory first. It is
not yet cartridge save-device emulation.

The output contains `game/*.cpp`, `native/` runtime source, `tools/extract_assets.py`,
`cmake/Runtime.cmake`, CMake, a README, runtime/tool licenses, a reviewed profile
and `pc-project.json`. Exact original identity, backend/runtime source revisions,
file hashes, fallback settings and experimental qualification are recorded.
Input files are preserved and existing output directories are rejected.

## Reviewed profile

The schema is `decomp.wtf.nds-static-profile/v1`. Fields are:

| Field | Meaning |
| --- | --- |
| `input_sha256` | SHA-256 of the exact original ROM |
| `processors` | `arm9` and `arm7` objects, each with an aligned integer `stack` address |
| `code` | Module name to a list of `{address, size, mode}` ranges; mode is `arm` or `thumb` |
| `hooks` | Optional explicit native service entries with `cpu`, `address`, `mode`, `service` |
| `observe_words` | Optional aligned guest RAM word addresses reported after execution |
| `save_region` | Optional `{address, size}` RAM checkpoint |

All addresses and sizes are JSON integers. Ranges refer to decoded guest RAM,
not cartridge offsets, and must exclude literal pools and data. Both header
entries must have a translation with the correct processor and instruction mode.
Module names come from DS inspection, including `arm9:ov1` for ARM9 overlay 1.
Unknown instructions stop generation with the processor, mode and guest address.

The only native binding is `load_overlay`. A reviewed resident function entry is
replaced explicitly with this ABI: r0 is processor 0 (ARM9) or 1 (ARM7), r1 is
overlay ID, and r0 returns 1. The service loads that reviewed module, clears BSS
and returns through LR with instruction-mode exchange. Its entry must be separate
from translated ranges. A retail SDK loader is not discovered or hooked automatically.
One overlay is active per processor; same-processor overlays can reuse addresses.
Resident/overlay overlap and cross-processor overlay overlap are rejected because
this runtime has no lifecycle model for them. Constructors are unsupported.

An executable original example is defined in `tests/fixtures/nds-static/` and
`tests/fixtures/nds_static.py`. To export it without needing a DS assembler:

```sh
uv run python -c "from pathlib import Path; import json; from tests.fixtures.nds_static import image; data, profile = image(); Path('original.nds').write_bytes(data); Path('reviewed.json').write_text(json.dumps(profile))"
```

The committed fixture encodings are reproducible from the CC0 assembly using
`tools/make_nds_static_fixture.py` and an installed ARM GNU toolchain. This
toolchain is needed only to regenerate those encodings, not for the tests or
the generated PC repository.

## Execution and limits

Decoding happens during generation. The emitted C++ implements the selected
integer operations directly and dispatches by reviewed guest address and mode;
there is no instruction interpreter, JIT or emulator process. Original code
bytes in `game/image.cpp` are used only to check module assets before loading.
They are never an execution fallback.

The current subset includes ARM integer/flag operations, shifts, conditional
branches, BX/BLX, multiplication, aligned word/byte transfers and block transfers;
Thumb includes integer/shift operations, branches, calls, stack operations and
aligned byte/halfword/word transfers. Many ARMv4T/v5TE instructions, privileged
state, status restoration, SWIs and coprocessors are unsupported. This is not a
complete implementation of either CPU's instruction set.

Guest memory is integer addressed, checked little-endian RAM: 4 MiB main RAM,
32 KiB shared RAM and 64 KiB ARM7 IWRAM. Both processors share the same buffers.
This does not model CPU access permissions, RAM mirrors, TCM or DS device maps.
Execution starts at the two ROM header entries with profile stacks, zeroed
registers/flags and a host harness return sentinel in LR. The scheduler alternates
one instruction per active CPU. It does not model DS cycle timing or interrupts.

Unknown execution targets, unsupported devices, writes to translated code,
unaligned accesses and exhausted budgets fail explicitly. Extracted code bytes
must agree with translation. Extraction checks the original hash and all decoded
module hashes before updating assets. A failed run does not publish a RAM save.

Ordinary early-layout original fixtures are supported. ARM9 at cartridge offsets
0x4000 or later is rejected until secure-area/retail decoding is integrated.
Overlay extraction retains the existing BLZ decoder, but compressed overlays
have not yet been execution-qualified in this adapter. Import support elsewhere
in decomp.wtf does not establish execution support here.

General DS PC export stays disabled in the GUI and `pc status` while this adapter
requires explicit experimental invocation. Next work includes retail module
decoding, CPU coverage, interrupts/timing, graphics, audio, input, cartridge/files,
save devices and compatibility checks on a chosen DQ or Pokémon title. The
[implementation plan](future/ds-native.md) tracks those milestones.

## Validation

```sh
uv run pytest -q tests/test_nds_pc.py tests/test_pc_output.py
```

The original fixture sends data between ARM9 and ARM7, calls Thumb code, swaps
two overlays at one RAM address and increments a persistent counter. Its final
registers, flags and RAM are compared with actual original-byte execution in
Unicorn 2.1.4. That test engine is a development dependency only. The original
loader executes its own copy routine in the oracle; the comparison does not
reuse the generated runtime's overlay service.

A changed input instruction must change the generated result. Another 75 ARM
and Thumb arithmetic/shift cases compare results and flags against original-byte
execution, including zero/32/oversized shifts and carry/overflow boundaries.
Checks also cover saves, a clean rebuild, wrong inputs/assets, unsupported
execution, profile errors and preservation of existing work. The dedicated
`DS static PC repository` workflow runs these tests on Windows and Linux.

Initial implementation `1913efd5af9a6ae1360def623d93d458e70ecff5` passed
[24 checks on each native host](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/40044562004)
with no skips. The [shared foundation checks](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/40044561894)
also passed on both hosts. A focused local run passed 55 checks, and a built
Python wheel independently generated a repository that extracted, compiled and
passed its CTest execution check. These results qualify the documented original
fixture path only; retail gameplay and DS hardware behavior remain outstanding.
