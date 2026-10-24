# PS2 native PC output

The experimental exporter in [PR #5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5)
builds on the DS and PS1 native output work. It produces one
standalone CMake source project with generated EE game code, source-shipped
runtime, locally extracted assets and adaptive GPU rendering. PS2 has one
screen. DQVIII is the first supplied retail validation input. Import, module
discovery, translation, runtime and export remain shared PS2 components; a
title-specific profile cannot qualify other games or replace generic support.

## Standalone export

The CLI and GUI share a source exporter. It ships generated EE C++, the pinned
GPL-3.0 runtime and SDL3 GS sources, checked CMake dependencies, an owner-asset
helper, retained code map and input hashes. No BIOS is needed. The host supplies
Vulkan geometry rendering, reported software fallback, required-GPU errors,
current-display startup, drawable/high-DPI resize, F11 native fullscreen,
keyboard/gamepad input, audio and per-project saves. Unknown/changed EE code
fails; IOP/VU interpretation is disclosed. Generation is not gameplay validation.

```sh
decomp pc ps2-native GAME.iso NEW_OUTPUT --experimental
python NEW_OUTPUT/tools/extract_assets.py /path/to/GAME.iso
cmake -S NEW_OUTPUT -B NEW_OUTPUT/build
cmake --build NEW_OUTPUT/build --config Release --target ps2_pc --parallel 2
```

The asset helper's `--reference` option verifies and retains the original disc's
absolute path without copying it. Boot and IOP files are extracted; other files
and original sector numbers stream from ISO/BIN. The default copies the disc for
portability. Existing destinations/assets and saves are preserved. Failed
emission retains diagnostics separately.

Install [Python 3.12+](https://www.python.org/downloads/),
[CMake 3.24+](https://cmake.org/download/) and an x86-64 C++20 compiler. Windows uses
[Visual Studio Desktop C++ Build Tools](https://visualstudio.microsoft.com/downloads/).
The output README lists Linux desktop/audio/FFmpeg development packages.
SDL3, raylib, shader tools and Windows FFmpeg libraries download with checked
hashes when required. Install a current GPU driver from
[NVIDIA](https://www.nvidia.com/Download/index.aspx),
[AMD](https://www.amd.com/en/support/download/drivers.html) or
[Intel](https://www.intel.com/content/www/us/en/download-center/home.html).

The optional GPL-3.0 DQVIII USA analysis profile is selected only for the exact
whole-disc hash below. It contains addresses/names and explicit SDK bindings,
without original instructions/assets. Other stripped games need `--profile
reviewed.json`; symbol-bearing original programs work without one. Maps must
distinguish code from data and declare native SDK bindings. The complete map is
retained as `game/profile.json`. Explicitly typed late constructor code and
alternate entries can reside in file-backed executable load memory even outside
the primary text section. Analysis ELFs preserve original load images. Owner
boot files stay unchanged. Function guards avoid comparing unrelated mutable
data in mixed writable segments.

The original standalone fixture has built/executed locally on Linux through both
Vulkan and software rendering. Generated EE code sends a triangle through GIF
DMA and GS, resizes the drawable from 320x320 to 640x480, and changes geometry
scale from 5x to 10x. Captures contain the expected triangle. Changed code and
missing required GPUs must fail. Static VU upper instructions have 288 value/flag
comparisons across direct helpers and actual emitted C++.
The [standalone workflow](../../.github/workflows/ps2-native-port.yml) builds the
output on Windows/Linux; Linux executes graphics and Windows checks required
device failures. Results apply only to the tested commit.

The runtime package pins PS2Recomp `888ec479165f41b899bb081e0ca7123b8c5af31a`
and the generic GS component from DQ8-Recompiled
`f6dfd968001b492415969bb70bd5aad3bfa79abd`. Game launchers, branding, address
hooks and menus are excluded. Archives and the resulting tree are checked by
[runtime-inputs.json](../../src/decompnet/ps2_native/runtime-inputs.json).
Integration fixes include FIO access flags, indexed disc lookups/reads, CD/DVD
medium and command-priority RPCs, static VU0 current/sticky flags, VF0's hardwired
value, disabled GS depth-test semantics and serialized GPU recording against
presentation/readback. Shared VU helper types and compact module dispatch avoid
compiler memory exhaustion when building large retail exports.

Original service programs verify bounded FIO reads/stat/seeks, original CD LBAs,
CD/DVD RPCs, pad edges/axes, 1,024 exact SPU2 stereo PCM samples and memory-card
write/reload across separate processes. These exercise the generated project's
actual runtime. They do not prove every IOP service, physical audio output or
retail save path. FFmpeg movie support is enabled in the standalone build.

The supplied DQVIII USA export emits all seven mapped modules with zero emission
errors and builds its standalone executable. A bounded 20-second native run
reaches the initial settings prompt with GPU geometry and streamed original disc
reads, without missing-function or execution errors. This uses the exported
host and generated game code; no title launcher or address hooks are imported.
It is boot evidence, not a full game or playthrough certification. Inputs, game
source, captures and detailed retail logs remain private.

## Candidate assessment

The first candidate is [PS2Recomp](https://github.com/ran-j/PS2Recomp), pinned to
`e5636981a1c9de368f6b71e819c3dc188dfedbf4`. Its Git tree is
`f53888c06d1cc37e9b87e25fea3c23d3ede5ea7e`. The optional source has GPLv3
terms, separate from this application's MIT license. It is not automatically
installed with decomp.wtf. The assessment pins emitter dependencies and raylib
to immutable commits in [inputs.json](../../tools/ps2_runtime/inputs.json).

The original CC0 fixture builds its own ELF32 and machine-code functions. The
developer assessment translates that ELF into actual C++, links the complete
candidate runtime, and compares 54 executions with an independent, bounded
interpreter of the original instruction words. It checks all 128-bit GPRs,
HI/LO, final PC and output RAM across word/wide arithmetic, signed/unsigned
loads, quadword memory operations, packed MMI operations, branch/likely delay
slots and direct/indirect calls. The runner starts no window and uses no BIOS,
retail code, original console compiler, instruction patches or return stubs.

These checks qualify CPU translation only. The integration guards every emitted
function entry against its own original executable sections, including direct
calls that bypass runtime lookup. The assessment alters code before dispatching
each of the 19 entries and requires a specific code-mismatch rejection. The
original candidate's generated table has no such guards. The shared registry
isolates each module's symbols and selects its implementation by original code
bytes, including internal resume entries. Two original variants contain 19
functions each at the same addresses. The assessment compares 60 original/native
states, including direct/indirect calls in the second variant and an A/B/A
resident switch. Unknown/mixed code is rejected. Separate original host sentinels
verify ambiguity rejection and that a failure after guest side effects propagates
without restarting another implementation.

Mutable executable sections and self-modification within a running function
remain unsupported. The registry is qualified through original memory-loaded
fixtures; retail loaders, constructor execution, BSS and runtime registration of
HLE replacements need integration checks. Missing dispatch stops.
No graphics, audio, IOP, vector unit, save, gameplay or general retail claim
follows from a CPU result. The newer standalone backend has its own qualification
path; the older CPU checks remain independent regression evidence.
Logs, generated sources, expected/actual state and the candidate license remain
in the assessment directory, including on failure.

The first [Windows/Linux qualification run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/40116366272)
passed all four assessment tests on each host, including all 54 native/original
execution comparisons. It translates 19 functions with zero stubs, skips or
decode failures. The fixture ELF SHA-256 is
`f4d4ff25d26efbc29445dbaa25de58fb2219d08bef4d8559cc4888791bb3e01b`.
This evidence covers the listed instruction subset, not the entire R5900 ISA.

Run from the app checkout with Python 3.12+, CMake 3.24+, Git and a C++20
compiler on x86-64 Windows or Linux:

```sh
python -m tools.qualify_ps2_runtime "/new/path/PS2 assessment"
```

The command fetches the pinned source into a new sibling directory and preserves
existing directories. For a previously downloaded, clean pinned checkout, add
`--sdk-root /path/to/PS2Recomp`. Linux requires raylib's desktop build headers:
`libx11-dev libxrandr-dev libxi-dev libxcursor-dev libxinerama-dev
libgl1-mesa-dev libasound2-dev`. Windows uses Visual Studio 2022 Desktop C++.
The dedicated workflow runs both hosts and fails if required tools are missing.
MPEG decoding is disabled for this CPU assessment; movie support is required
before qualifying a game runtime.

## Disc preparation and DQVIII findings

`decomp pc ps2-inspect GAME.iso` inspects a PS2 ISO/BIN or standalone EE ELF
without installing a compiler or runtime. It streams the image, hashes the
original input, follows BOOT2, records ordered ELF load segments and inventories
IOP modules. `--quick` skips the whole-image hash and explicitly reports that
full input identity is unverified. It does not generate or qualify a game.
Original tests exercise nested paths, sparse DVD extents above 4 GiB, stripped
ELFs, overlapping zero-fill BSS loads, malformed/truncated layouts and input
changes during inspection. Unsafe or unsupported ISO layouts fail explicitly.

Add `--discover-code` to trace bounded R5900 control flow from the ELF entry,
function symbols and discovered direct calls. It records reachable byte ranges,
direct-call seeds, system-service sites and unresolved indirect/external targets.
Branch delay/likely behavior, linked branches and zero-link `JALR` are covered
by original fixtures. Instruction and symbol bounds fail explicitly. This is
preparation evidence, not a complete function map or gameplay qualification.
No compiler or runtime is installed by either inspection mode.

Metrowerks MWo3 overlays are recognized from their own headers, with independent
hashes, load/text/data/BSS extents and constructor tables. An overlay can be
wrapped for analysis as an ELF while preserving its entire original load image
and marking only its declared text executable. This adapter has no title table
or fixed load address. Its synthetic ELF entry marks the start of text; it is
not evidence of a standalone module entry or complete function recovery.
With code discovery requested, in-module constructors also seed overlay analysis;
the synthetic text-start root remains labelled. Calls into the main executable
stay explicit external targets. The [MWo3 format reference](https://github.com/Sinan-Karakaya/DQ8-Recompiled/wiki/File-Formats)
documents the format; this adapter has no DQVIII-specific load table.

The privately supplied USA DQVIII archive contained all 252 volumes and passed
its archive CRC check. The ISO is 4,180,148,224 bytes, SHA-256
`a38f71b7a02f1ae0fe65cc78137ee9c943b75b44473ae1cd5ed89ef0e61400e9`.
Its boot program is `SLUS_212.07` (2,960,032 bytes), SHA-256
`56ac18170704111c9cbf2f3a8a71ee5b708f39706649671ca1b1314451ef9c28`.
It has no function symbols, six overlapping zero-file-size ELF reservations and
16 IOP IRX modules. The generic parser independently discovers six MWo3 overlays;
each matches one reservation exactly. These are input facts, not boot/gameplay
evidence. Original fixtures verify shared-address modules with different IDs,
hashes and load addresses, including cached/uncached EE aliases.

The unmodified candidate's initial function scan reported 8,314 functions and
zero decode failures, but its separate emission report contained 7,948 errors.
It still returned success. Many diagnostics came from interpreting embedded
data as instructions. The integration now requires a complete diagnostic report
and rejects emission errors even when exit status and decode counts say success.
The original CPU fixture still has zero emission errors. Stripped discovery alone
does not provide a complete retail translation map; the newer exporter uses an
explicit input-bound profile for this case.

The bounded shared control-flow pass reaches 56,195 instructions and 961 function
seeds in the stripped boot ELF, with zero invalid instructions and 81 unresolved
indirect sites. It avoids the later embedded-data region that caused the initial
emission errors. Indirect callbacks, jump tables, further roots and complete
function boundaries still require resolution; these seeds do not replace a
complete translation map.

Wrapping the six discovered overlays with the shared MWo3 adapter yields 1,146
emitted functions in the initial candidate scan, with zero emission errors,
stubs, skipped functions or decode failures (110 warnings). This records source
emission only: function completeness, compilation, module switching and execution
still need validation. No reviewed DQVIII address map was supplied to this scan.

## Qualification scope and remaining compatibility work

The separate GS assessment uses optional LGPLv3+ [paraLLEl-GS](https://github.com/Arntzen-Software/parallel-gs)
at `cc6184af7e0c03da603045ca371ffa5dae9b0655`, with Granite and four required
dependencies pinned by commit/archive checksums. It builds the Vulkan compute
renderer and sends original PACKED triangle and IMAGE GIF packets. Assertions
check exact coverage, image uploads with FLG=2/3, local-to-host VRAM readback and
a GS resolution change from 64 to 128 pixels. This is GPU renderer code, not
CPU rasterization presented through a GPU window. The local execution device is
Mesa llvmpipe (software Vulkan); reports identify that limitation explicitly.

Run `python -m tools.qualify_ps2_graphics /new/assessment` to download and assess
the pinned source, or add `--sdk-root /existing/pinned/source`. `--build-only`
qualifies compilation without claiming device execution. Linux CI executes the
original Vulkan commands on an explicitly selected software device. Windows CI
builds the same C++ probe and verifies required-device failure; its lack of an
execution device is recorded as `vulkan_executed: false`. No game graphics,
physical GPU, window/drawable adaptation or fullscreen qualification follows
from this headless assessment. Those remain required integration work.

The candidate supplies an EE runtime, R3000A IRX execution with IOP kernel/HLE
services, VU interpreters, GS, audio and virtual filesystem code. Those are
reuse candidates whose behavior needs original execution tests. Its current
`GSRasterBackend` implementation is `GSCpuBackend`: CPU rasterization followed
by host presentation. A GPU window displaying a software framebuffer does not
satisfy our [GPU geometry contract](../pc-output.md#shared-gpu-presentation-standard).

- [x] Qualify the original EE instruction fixture through native Windows and Linux builds.
- [x] Stream disc/module inventories and bounded direct-control-flow seeds from
  owner input, retaining exact identities and unresolved-target reports.
- [x] Require reviewed stripped ELF maps covering code/data, indirect callbacks
  and function boundaries; retain exact-input profiles in exported projects.
  General automatic recovery of complete maps remains future work.
- [x] Guard module/function entries, reject unresolved or ambiguous dispatch and
  disclose IOP/VU interpreters in manifests. Original module-switch fixtures
  cover overlapping addresses. Runtime self-modification is unsupported.
- [ ] Qualify IOP/IRX loading, SIF RPC/DMA, VU0/VU1, VIF/GIF and scheduler/IRQ
  behavior with original programs. Do not silently replace game logic with
  `ret0`, `ret1` or skipped wrappers.
- [x] Implement GS GPU geometry rendering with correct texture/readback/transfer
  synchronization, automatic reported software fallback, required-GPU errors,
  current-monitor startup, drawable resize/high-DPI and native fullscreen.
- [x] Qualify original input, SPU2 mixing, filesystem/CD/DVD reads and memory-card
  save/reload. Keep BIOS out of exports and enable FFmpeg movie support.
- [x] Generate a standalone repository with pinned runtime/dependency identities,
  asset extraction, supported input hashes and honest execution reports.
  Windows/Linux CI builds the output; Linux executes graphics, while Windows
  checks explicit required-device failure without claiming GPU execution.
- [x] Build the supplied DQVIII export and validate bounded boot/rendering/disc
  access through the exported host.
- [ ] Validate further DQVIII gameplay, overlays, movies, audio and retail saves.
  Final playthrough acceptance belongs to the user.

## Preserved work

Existing EE-GCC 2.96 matching, native Windows compiler hosts and exact ELF
reconstruction remain available. Their tests are separate from PC runtime
qualification. The exact GNUPro compiler-source investigation and whole-disc
repacking do not block this native-output milestone. [ico-pc](https://github.com/nathanialf/ico-pc)
is a game-specific product reference; its ICO bindings do not establish DQVIII
support. No original game assets, BIOS, SDK payloads or generated retail source
belong in this public PR.
