# PS1 native PC output

DS native output merged in [PR #29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29)
at `9b5440283bd90472edc029d4a1be3f8cfd1ad661`. PS1 is the active platform in
[PR #30](https://github.com/OMGitsMatt45/decomp.wtf/pull/30).
The first retail target is DQVII: **one source repository and build for both
ordered discs**, with runtime disc switching and shared saves. The existing
disc parsers, reviewed module placements and private source checkpoints remain
inputs to that work. Exhaustive matching recovery stays paused in PR #26.

## Optional runtime candidate

The first assessment uses [PSXRecomp](https://github.com/RetroPortingToolKit/psxrecomp),
pinned to `31df2e1e0e0a6525733e68ff70e72ecbef84bb09`:

| Item | Pin / finding |
| --- | --- |
| [Source download](https://codeload.github.com/RetroPortingToolKit/psxrecomp/tar.gz/31df2e1e0e0a6525733e68ff70e72ecbef84bb09) SHA-256 | `3376c1bf0509ca7045e92d0673ecbc9245084e017ffaa66d954c77519972d171` |
| Recompiler, codegen scripts, runtime headers and license fingerprint | `28937b3662e511935ecf986e7f0c1374a10d5068842504ef9c3a6731383b8a5b` |
| Emitter code-generation identifier | `115b1739` |
| [Candidate license](https://github.com/RetroPortingToolKit/psxrecomp/blob/31df2e1e0e0a6525733e68ff70e72ecbef84bb09/LICENSE) | PolyForm Noncommercial 1.0.0; separate from this application's MIT license |
| Candidate's default execution model | Hybrid: static C, interpreter fallback, runtime code compilation |
| BIOS | Bundled MIT OpenBIOS, executed by the original hardware fixture; no retail BIOS required |

The dependency is optional and is not installed by application setup. Its native
adapter is registered as experimental. Its noncommercial terms remain visible in the integration
and generated output. This assessment does not change decomp.wtf's MIT license
or establish commercial use rights for the candidate. The default hybrid model
is reported honestly. This integration disables runtime guest-code compilation
and retains the interpreter fallback.

## Implemented execution proof

`tools/qualify_psx_runtime.py` verifies the pinned source and emitter, builds the
emitter when needed, and generates C from an original CC0 PS-X EXE. A native
CPU-only host executes that generated code; an independent Unicorn instance
executes the original MIPS bytes. Twenty cases compare all general registers,
return PC and an observed RAM word, covering signed branches, call/return delay
slots, argument changes, calls and RAM reads/writes. Changed code must be rejected
by native dispatch. This probe links no interpreter or runtime compiler.

An integration patch anchors the generated MSVC `.CRT$XCU` startup marker with
external linkage and a linker reference. Actual Windows execution caught its
removal as an unused static pointer, including with `/OPT:NOREF`; compiling the
candidate alone had not exposed that failure. Reports record the generated
file's before/after hashes, and execution requires the marker to initialize.
The external candidate checkout stays unchanged. The complete runtime integration
also applies this fix to every game module and the BIOS initializer.

The harness supplies bounded RAM, disabled interrupts and an immutable-code guard.
It does not qualify the candidate's dirty-memory implementation, full R3000
pipeline, cycle timing, GTE, peripherals or GPU. The memory case includes a NOP
after its load; Unicorn's MIPS32 execution is not an oracle for R3000 load-delay
hazards. The assessment records `hardware_runtime_qualified: false` and
`retail_qualified: false`. This is a CPU integration proof, not a playable port.

From a developer checkout with Python 3.12+, CMake and a native C/C++ compiler:

```sh
uv sync --locked --group dev
uv run python -m tools.qualify_psx_runtime /path/to/new-proof --sdk-root /path/to/new-candidate --download-sdk
```

The helper automatically downloads only the pinned archive above. To reuse an
existing verified source tree, omit `--download-sdk`. `--recompiler PATH` can
reuse its built emitter; the code-generation identifier is checked before use.
Existing proof directories are preserved. Reports include execution boundaries,
input hash, pins and logs; retained generated C can be rebuilt after publication.
Original probe sources are CC0; external/generated helpers retain candidate terms.

The `PS1 native runtime candidate` workflow builds and runs this proof on Windows
and Linux, including a fresh rebuild from the retained output. No game, retail
BIOS, proprietary SDK or recovered game source enters the workflow.

## Hardware integration

The development standalone project has executed an original two-disc ISO fixture
against the complete runtime. Observed checks include native guest dispatch,
CD reads of the expected 2048-byte payload on each disc, nonzero SPU audio,
memory-card writes and a save reloaded after booting the other disc. A real
OpenGL 4.5 Mesa run rendered geometry into a 960×720 drawable at internal scale 3.
This fixed size was a test setting; the requested product behavior remains
adaptive to the user's current display.

An original fixture whose SYSTEM.CNF contains only BOOT exposed an OpenBIOS
configuration issue: missing EVENT/TCB/STACK values remained zero. The development
integration initializes their documented defaults before the existing parser
handles explicit values. A regression fixture must retain the omitted settings.

The standalone exporter and CLI/GUI/connected-agent paths are implemented in this
branch. A fresh source export additionally passed native/interpreted guest
comparison, a live tray change retaining the resident native module, adaptive
OpenGL resize to 1200×900, portrait, native-monitor fullscreen and reported
software fallback. Windows/Linux CI builds and executes original fixtures from
the exported source. Targeted DQVII evidence and full playthrough acceptance
remain separate from the original qualification.
The shared GPU requirement is documented in the
[PC output specification](../pc-output.md#shared-gpu-presentation-standard).

## Qualification scope

The [implemented guide](../ps1-native.md) records the source export and execution
model. Original CPU and hardware fixtures exercise different boundaries;
neither proves all GTE operations, every peripheral, accurate timing for every
title, all controller models or general retail compatibility. DQVII's reviewed
archive/module facts are reused when exporting its retained project. Targeted
automated checks should gain original regressions when they expose a runtime
failure. The user owns full playthrough acceptance.

Do not substitute reconstruction success, matching percentages or CMake
configuration for native game execution. A generally useful translator/runtime
can support many titles while still requiring specific loader and compatibility
fixes; no full-game or universal compatibility claim is made by this assessment.
