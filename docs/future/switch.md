# Switch source integration

Switch source export is available through four explicit development commands:
`switch-inspect`, `switch-probe`, `switch-runtime` and `switch-native`.
The desktop export translates guest AArch64 into editable C and bundles Kirikae's
host services, threads, Maxwell shader translator, Vulkan renderer, audio,
controllers and filesystem sources. Its normal build excludes the CPU
interpreter and rejects missing native targets instead of falling back.

The desktop exporter is qualified on original programs on Linux x86-64.
It retains a v2 `cpu-probe` development manifest: the shared adaptive game
presentation contract, Windows execution and retail gameplay are unqualified.
The five advertised game-output backends therefore remain separate. Status for
Switch identifies the development commands and their scope.

## Sources pulled together

Four complete upstream trees are pinned in
[`sources.json`](../../src/decompnet/switch_native/sources.json), each with its
commit, archive SHA-256, license and current role:

| Source | Integrated use | Remaining work |
| --- | --- | --- |
| [nxport](https://github.com/nxporting/nxport) | Pinned dependency-free Rust lifter; editable C, CPU ABI and multi-module dispatcher; desktop adaptations add guest-memory translation and cooperative polling | Broaden ISA and static discovery coverage per title |
| [LASRecomp](https://github.com/peiikai/LASRecomp) | CPU/SIMD semantics inherited through nxport; original emitter built for independent scalar comparisons | Extract generic services/graphics from the title-specific runtime |
| [Kirikae](https://github.com/Cor3Duo/kirikae) | Source-shipped loader, threads, Horizon/services, audio/input/saves, Maxwell/SPIR-V and Vulkan runtime; checked C/Rust CPU bridge, strict failures and renderer reporting | Adaptive geometry rendering, additional SDK startup paths and per-title service coverage |
| [nxrecomp](https://github.com/drakolordx7/nxrecomp) | External GPL scalar lifter built and run as a comparison oracle | Evaluate runtime components and retain applicable GPL terms if incorporated |

These sources have different CPU structures, dispatch protocols and host
callbacks. The emitter uses the nxport/LAS ABI. The small probes have a bounded C service
adapter; the desktop exporter bridges this ABI to the full Kirikae host runtime. The generated project contains the runtime
source it actually uses and retained MIT notices. GPL donor code stays in the
separate development tree and comparison build directory.

Fetch or verify all four full source trees, without running their installers:

```sh
uv run --locked python -m decompnet.switch_native.sources /path/to/switch-sources
```

The helper verifies the immutable archives and compares an existing checkout
against them. Edits are preserved; a mismatch is reported instead of replacing
the checkout. Archive and extracted-size limits apply. The small production
emitter source is vendored, so exporting a CPU project needs no network or Cargo
dependency resolution.

## Build an original program

Export requires Rust 1.90+ (`rustc` on PATH or `DECOMP_SWITCH_RUSTC`). Building an
export requires CMake 3.20+, Clang for GNU C with `__int128`/`musttail`, and a
C++20 host compiler. Rust and the donor trees are not required to build the small probe or bounded
service export. The desktop export below requires Rust as well. These initial builds are qualified on Linux x86-64; Windows
execution remains unqualified.

```sh
uv run --locked python tools/switch_fixture.py /tmp/original.nso
uv run --locked decomp pc switch-inspect /tmp/original.nso
uv run --locked decomp pc switch-probe /tmp/original.nso /tmp/switch-source --experimental
cmake -S /tmp/switch-source -B /tmp/switch-build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/switch-build --parallel
/tmp/switch-build/switch_probe /tmp/switch-source/assets/image.bin /tmp/switch-run.json
uv run --locked decomp pc verify /tmp/switch-source
```

Choose unused output paths. `tools/switch_fixture.py --nro` writes the same
original program as NRO; `--compressed` writes independently LZ4-encoded NSO
segments. The checked-in assembly, linker script and machine-code hex live
under `tools/fixtures/switch-cpu.*`. To regenerate the hex, compile the assembly
for `aarch64-linux-gnu`, link with `switch-cpu.ld` and entry `_entry`, then write
the `.text` section bytes as hex. The original code and fixtures use MIT.

An export contains `game/*.c`, `runtime/`, `assets/image.bin`, CMake, source pins,
translation/discovery reports and a v2 PC-project manifest with
`output_kind: cpu-probe`. Missing targets, unsupported instructions/services,
asset-hash mismatches and changed function-entry code produce failing reports.
There is no instruction interpreter or runtime guest-code compiler. Generated
text is guarded at function entry; self-modification within a function and
dynamically loaded modules are unsupported. Fixed guest/host pointer mappings
make this a trusted local development harness, not an isolation boundary.

## Linked ExeFS and service runtime

Use an extracted `exefs`/`ExeFS` directory, or its parent. Modules are selected
in the fixed order `rtld`, `main`, `subsdk0` through `subsdk9`, `sdk`; `.nso`
suffixes are accepted. Duplicate names and module symlinks are rejected. The
loader validates NSO segments and MOD0 tables before compiling anything.
Dependencies resolve through module filenames, ELF SONAMEs and bounded Nintendo
rodata module-name records. Embedded build paths and `.nss` suffixes are
normalized as library identities; conflicting identities are rejected.

The linker supports bounded SysV/GNU hash tables, strong/weak and local/hidden/
protected symbols, `DT_SYMBOLIC`, `R_AARCH64_ABS64`, `GLOB_DAT`, `JUMP_SLOT`,
`RELATIVE`, and packed RELR relocations. It verifies initializer pointers and
runs dependency-ordered `DT_INIT`/`INIT_ARRAY` constructors. Unsupported
relocations, symbol versions, TLS/indirect-function bindings, unresolved strong
imports and missing `DT_NEEDED` dependencies are errors. Undefined weak symbols
resolve to zero before their relocation addends are applied.

An extracted ExeFS can include `switch-link.json` for code mods that require
4 KiB module packing and have reviewed symbols in stripped modules. Set
`schema` to `decomp.wtf.switch-link/v1`, `alignment` to `4096`, and `inputs`
to a map of every selected input filename to its SHA-256, including `main.npdm`
if present. Optional `imports` maps a missing strong symbol to an object with
`module` and module-relative `offset`. Optional `entries` maps module names to
lists of module-relative executable entry offsets. Offsets are JSON integers.
The loader checks both declared offsets and relocated addresses against the
owning segments. Calls and function pointers require aligned executable text.
ELF exports take precedence. The profile's bytes are included in the input identity.
An ExeFS without a profile uses the existing 64 KiB alignment.

Static function discovery also reads MOD0's `.eh_frame_hdr` search table. This
recovers stripped function entries that symbols, relocations and address
materialization miss. Header ranges, DWARF pointer encodings, entry counts,
executable addresses and FDE pointers are checked before translation. Tables
use each module's linked base; addresses from another game's symbol map or
another build must not be reused without verification.

The host applies relocations before translating code and bypasses guest `rtld`
execution. When a module exports `nn::init::Start`, the desktop runtime enters
that SDK startup ABI with the main-thread handle and two constructor callbacks.
The SDK initializes OS/thread state before the SDK DSOs, then initializes the
application heap before the main DSO. Nintendo-style `DT_INIT` owns its
`INIT_ARRAY`, so the callbacks do not invoke that array a second time. The
selected `nn-sdk-start` plan is recorded in `analysis.json`. Inputs without
that SDK export retain the bounded host-linked entry/constructor model. This
does not establish complete Nintendo SDK process-startup compatibility.
`main.npdm`, if supplied, is hashed
and provides a bounded stack size. Each original module remains separately
identified in the manifest; generated assets contain the linked memory images.

Build the original multi-module fixture:

```sh
uv run --locked python tools/switch_exefs_fixture.py /tmp/original-exefs
uv run --locked decomp pc switch-inspect /tmp/original-exefs
uv run --locked decomp pc switch-runtime /tmp/original-exefs /tmp/switch-runtime-source --experimental
cmake -S /tmp/switch-runtime-source -B /tmp/switch-runtime-build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/switch-runtime-build --parallel
/tmp/switch-runtime-build/switch_runtime /tmp/switch-runtime-source/assets /tmp/switch-runtime-run.json
```

The bounded source runtime provides a main stack and TLS, heap growth up to
4 MiB, main-thread identity, a monotonic 19.2 MHz clock, debug output, process/
thread exit, handles, and a HIPC/CMIF subset. `sm:` initializes and opens `set`;
`set:GetLanguageCode` returns the explicit development locale `en-US`. Requests
can use TLS or a checked user buffer. Invalid handles return the Horizon error;
other unsupported services, commands, domains, descriptors and invalid pointers
stop with an execution report. `QueryPointerBufferSize` reports zero instead of
advertising unsupported descriptor storage. This is not a complete kernel.

Every module asset is verified before constructors run, and each module's code
is guarded at translated function entry. Reports include per-module native
counts, constructor/SVC/IPC counts, registers and bounded data samples. Owner
source changes during export prevent publication and remain intact.

On Windows, full-file SHA-256 checks stream through the system CNG provider,
including multi-gigabyte RomFS images. Read/provider errors reject the asset.
The desktop link includes the windowing runtime's IME, DWM and theme libraries.

## Desktop source runtime

```
uv run --locked decomp pc switch-native /path/to/exefs /path/to/new-source --experimental
cmake -S /path/to/new-source -B /path/to/new-build -DCMAKE_C_COMPILER=clang -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/new-build --parallel
/path/to/new-build/switch_native --assets /path/to/new-source/assets --report run-report.json
```

A standalone NSO is host linked with the same relocation checks; unresolved
imports require the complete ExeFS. Homebrew NRO loads at `0x08000000` and runs
its own startup code. Desktop builds require Rust 1.95+, Clang 18+, CMake 3.20+,
a C++20 compiler and, on Linux, ALSA/udev development packages.
On x86-64, builds enable CMPXCHG16B for 128-bit guest atomics. The exported
`sdk/Cargo.lock` pins external Rust dependencies. Cargo downloads these packages
on first build; source export itself is offline. Every upstream runtime source
is verified before the checked adaptations are applied to a private copy.

Use an optimized build for large inputs: SIMD helpers rely on optimization to
fold constant operation and lane choices. For an initial compilation check,
`-DCMAKE_C_FLAGS_RELEASE="-O1 -DNDEBUG -g0"` reduces optimization work. Limit
parallel compilation to fit available memory; an unoptimized retail build can
expand these helpers enough to exhaust it.

`--romfs /path/to/romfs.bin` during export includes an owner-extracted RomFS image.
For an updated title, pair the updated ExeFS with the merged RomFS from the same
build. Package decryption and BKTR merging happen in a separate extraction tool
before export. The RomFS hash participates in the input identity and is checked
before guest execution.

When merging a BKTR patch with hactool `--baseromfs`, first extract the decrypted
base RomFS section with `--raw --romfs=base-section.bin`. This also works for a
rights-managed base that you decrypt separately. BKTR offsets refer to the
entire base section, including the IVFC hash levels. Pass that raw section as
`--baseromfs=base-section.bin` and save the merged patch section with
`--sectionN=romfs.bin`, where `N` is the reported BKTR section number. Omit
`--raw` on this second command to produce the plain image for `--romfs`.
[hactool's BKTR extraction notes](https://github.com/SciresM/hactool/issues/50)

`--feedback run-report.json` adds missing targets in the exact input's code to the
next static export. Foreign inputs and targets outside its executable modules
are rejected. Re-export to a new directory to preserve source edits.

The player accepts `--renderer auto|vulkan|software`, `--saves PATH`, `--headless`
and the development bound `--frames N`. Software selects a Vulkan CPU device and
is explicitly reported. GPU initialization, unsupported shaders, skipped draws,
missing services/SVCs, memory faults and changed assets produce failing reports.
An audio-device open failure is reported when audio is requested. Reports include
native entry counts, zero-interpreter statistics, constructors, final main-thread
registers and bounded module data samples. Guest worker threads finish before
runtime shutdown. The bridge preserves registers, memory addressing, reentrant
HLE calls, cooperative scheduling and host/guest floating-point environments.

The window starts at monitor size; F11 toggles fullscreen and resizing updates
the drawable. Current Vulkan geometry targets still use guest dimensions.
Resizing a swapchain does not establish the shared drawable-resolution geometry
contract. That is why this remains an explicit development export.

Keyboard: WASD/arrows left stick, IJKL right stick, Z/X/C/V face buttons,
E/U shoulders, Q/O triggers, Enter plus, Backspace minus. Gamepad and HID sources
are included. Saves use a title namespace below the host data directory's
`decomp.wtf/switch/saves`, or the supplied save root. An NPDM title ID is used
when available; otherwise the exact input identity supplies a namespace.

Use **Add an existing PC project** in the app to track the exported folder,
read its build instructions and verify source integrity. Switch uploads route to
the explicit development command instead of another console's generator.

## Validation

[`tests/test_switch_native.py`](../../tests/test_switch_native.py) builds and
executes the fixture from plain NSO, compressed NSO and NRO. It compares every
general and vector register, NZCV and a data sample against independent Unicorn
execution. The fixture includes a factorial loop, stack/call returns, carry and
32-bit zero extension, FP addition, vector arithmetic/stores and an indirect
call discovered through ADR. Explicit expected results include `x0 = 150`,
stored factorial `120`, float `3.5` and four vector lanes equal to `16`.

Negative runs exercise changed-code and missing-target failures without
interpreter execution, changed assets before guest execution, malformed headers,
segment overlap, hashes and bounded LZ4 decoding. Other checks preserve existing
outputs, detect modified vendored sources and retain developer edits in pulled
trees. Standard PC-output and platform-scope checks run alongside them.

For source-specific comparison builds:

```sh
uv run --locked --group dev python tools/qualify_switch_sources.py \
  --sources /path/to/switch-sources --work /path/to/new-comparison-build \
  --rustc /path/to/rustc --cc /path/to/clang
```

That command verifies all donor trees, builds/runs 20 nxport lifter tests and
15 Kirikae loader tests, and compares LASRecomp/nxrecomp scalar output against
independent unsigned arithmetic on 2,304 cases. Those cases cover nine integer
instruction forms on 256 edge-value input pairs. This is bounded evidence, not
exhaustive AArch64 validation. The original complete-program tests supply the
separate floating-point, SIMD, memory and control-flow evidence.

The recorded initial run is in [switch-native-validation.json](../switch-native-validation.json).

[`tests/test_switch_exefs.py`](../../tests/test_switch_exefs.py) additionally
compares linked images against independently specified relocation values and
executes a two-module original program. The SDK constructor writes `7`; the
dependent main constructor adds `5`; a cross-module call adds `30` and returns
`42`. The program exercises heap/thread/debug services and SM/settings IPC,
including PID headers, moved handles, tokens, a user buffer and invalid-handle
errors. Deterministic registers and memory match independent Unicorn execution
with fixture-specific SVC replies. The live host-clock timestamp is checked for
positivity and excluded from exact equality.

Negative native runs cover a changed second module, missing target, changed
assets before initialization, unsupported SVC/IPC/descriptors, malformed IPC,
and invalid service memory. Separate original variants exercise process exit
and the zero pointer-buffer capacity reply. Linker checks cover GNU hashes,
packed RELR bitmap/BSS writes, local symbol precedence, dependency cycles,
constructor forms, invalid metadata and edits during export. The current run is
recorded in [switch-runtime-validation.json](../switch-runtime-validation.json).

## Desktop qualification

Run the reproducible qualification with installed Rust, Clang, Cargo and CMake:

```
uv run --locked --group dev python -m tools.qualify_switch_desktop \
  --work /path/to/new-validation --graphics
```

`--graphics` needs a Vulkan 1.3 CPU driver, such as Mesa llvmpipe. `--offline`
uses already cached Cargo dependencies. Compiler paths can be supplied with
`--rustc`, `--cc`, `--cmake` and `--cargo`. The command preserves existing work,
exports fresh source trees, builds them and records each result and its hash.
`--resume` rechecks unedited source and input identities before continuing an
interrupted build in its existing work directory.

The arithmetic fixture prints the expected sum, indirect square, branch-table
result and recursive Fibonacci value. Both serialized and parallel worker
fixtures print `threads: 40400`. The two-module fixture runs both constructors
and returns `42`. An original SDK-start ABI fixture checks deferred constructor
callbacks and `DT_INIT` ownership of its array; it also returns `42` with exactly
two constructor calls. Original FP/SIMD programs return `150`, store factorial `120`,
float `3.5` and four vector lanes of `16`, from both NRO and compressed NSO.
A separate original fixture checks LDXP/STXP and LDAXP/STLXP: both stores
succeed and leave the expected 128-bit pair `(0x13, 0x24)`. All run through
native C with zero interpreted instructions. Negative runs cover
untranslated targets, unsupported SVCs, guest memory faults and changed assets
before native execution. A combined native/interpreter feature build is rejected.

A computed-branch fixture also enters the block immediately after a conditional
branch and returns `42`, matching independent Unicorn execution. Unresolved
computed branches retain these fallthrough addresses as dispatchable block
starts, in addition to their taken targets and unconditional block boundaries.

The source runtime passes 213 unit tests, including audio mixing/resampling,
input/HID, synchronization and filesystem/RomFS behavior. A separate host GPU
qualification submits real Maxwell pushbuffers and vertex/fragment shader code
through the game's Vulkan path. Readback contains exactly 3,456 red pixels at
128x96 and 13,824 at 256x192, with a red triangle center, black outside pixels
and zero skipped draws. This is GPU runtime evidence, separate from guest CPU
execution. The recorded device is Mesa llvmpipe, a software Vulkan device.
The [256x192 readback](../assets/switch-maxwell-triangle.png) is retained with
the validation record.

See [switch-desktop-validation.json](../switch-desktop-validation.json) for the
record. Physical GPU/audio/controller hardware, Windows, adaptive geometry,
retail SDK startup and complete gameplay remain unqualified. Static discovery,
unsupported instructions, dynamically loaded code, additional Horizon/NVN
services and shader coverage remain per-title development work. These limits
are explicit in source manifests and do not prevent building or editing the
qualified source exports.

## Desktop application sessions

The exported runtime retains foreground applet focus/capture/suspension policy,
expected applet audio volumes, and the initialized game-facing parental-control
session. No console parental-control database is imported or host policy changed.
HID activation and disconnects update controller publication, assignment policy
is retained, and virtual handheld activation uses the SDK's aruid-first ABI.
Idle peripheral samples, vibration request/readback and stationary IMU lifecycle
are implemented for virtual controllers; physical rumble and motion are not
qualified. Unsupported requests continue to stop strict native runs.
Short keyboard taps span at least 50 ms and two presented frames so games
can observe them during slow rendering. A 500 ms cap prevents a stalled display
from retaining a tap. Holds that already span those frames release immediately;
headless input keeps the 50 ms minimum. Focus loss clears all input. Set
`KIRIKAE_INPUT_TRACE=1` to log key events and sampled button transitions.

Native builds compile missing graphics pipelines synchronously before drawing.
This prevents the asynchronous compiler's pending state from discarding draws
on transient targets. Compilation errors and unsupported shaders remain fatal.
The Windows Switch workflow executes native CPU/module comparisons, original
desktop programs and runtime regressions without retail game inputs.

The Vulkan runtime maps the Maxwell window-origin mode and its separate
`FLIP_Y` flag to the host front-face convention. The original graphics probe
checks both windings across both origin modes, both flip states, and both
viewport-height signs. [NVIDIA's Maxwell register definitions](https://github.com/NVIDIA/open-gpu-doc/blob/master/classes/3d/clb197.h#L2305-L2311)

The original `prepo:u` play-report commands `10100` and `10101` copy guest report
buffers into a bounded process-local queue. They do not contact Nintendo or
claim successful uploads. The queue holds at most 16 reports and 1 MiB total;
malformed or unmapped buffers are rejected. Unknown commands still take the
strict unsupported-service path. These changes pass 215 runtime unit tests.

The normal software-keyboard applet now opens a Windows text-entry dialog.
Guest storage objects resolve through both domain IDs and session handles;
the keyboard reads the applet's prompt, initial UTF-16 text and length bounds.
Its native output storage reports acceptance or cancellation instead of
returning a fixed trainer name. Headless runs cancel unless explicitly supplied
`DECOMP_SWITCH_KEYBOARD_TEXT`; supplied text must meet the guest's bounds.
The original fixed string is retained only inside the synthetic unit fixture.
ABI fields follow [libnx's software-keyboard definitions](https://github.com/switchbrew/libnx/blob/master/nx/include/switch/applets/swkbd.h).

A launcher can opt into a PC settings handoff with
`DECOMP_SWITCH_SETTINGS_MENU=1`. On Windows, F10 asks whether to close the game
and return to the launcher, warns about unsaved progress and defaults to No.
Acceptance follows the normal window-close shutdown path; the execution report
records `host_action: "settings"`. Save editing belongs to the launcher after
the process exits. No dialog is opened in headless runs, and strict failures
still determine the run's status. The source runtime passes 219 unit tests.
