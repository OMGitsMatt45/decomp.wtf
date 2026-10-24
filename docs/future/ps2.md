# PS2 native PC output

Implementation work continues in [PR #5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5),
based on main after the DS and PS1 native output merges. The target is one
standalone CMake source project with generated EE game code, source-shipped
runtime, locally extracted assets and adaptive GPU rendering. PS2 has one
screen. DQVIII is the first supplied retail validation input. Import, module
discovery, translation, runtime and export remain shared PS2 components; a
title-specific profile cannot qualify other games or replace generic support.

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
original candidate's generated table has no such guards. Mutable executable
sections and self-modification within a running function remain unsupported;
module switching needs a separate guarded registry. Missing dispatch stops.
No graphics, audio, IOP, vector unit, save, gameplay or general retail claim
follows from a CPU result. The app does not register a PS2 PC backend yet.
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

Metrowerks MWo3 overlays are recognized from their own headers, with independent
hashes, load/text/data/BSS extents and constructor tables. An overlay can be
wrapped for analysis as an ELF while preserving its entire original load image
and marking only its declared text executable. This adapter has no title table
or fixed load address. Its synthetic ELF entry marks the start of text; it is
not evidence of a standalone module entry or complete function recovery.

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
The original CPU fixture still has zero emission errors. Stripped function and
code/data discovery needs further work before this retail output can be built.

Wrapping the six discovered overlays with the shared MWo3 adapter yields 1,146
emitted functions in the initial candidate scan, with zero emission errors,
stubs, skipped functions or decode failures (110 warnings). This records source
emission only: function completeness, compilation, module switching and execution
still need validation. No reviewed DQVIII address map was supplied to this scan.

## Runtime work required before game output

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
- [ ] Automate stripped ELF function discovery, code/data boundaries and module
  inventories from the owner's disc, retaining exact input identities.
- [ ] Add per-module original-byte guards and explicit handling of overlays,
  unresolved dispatch, self-modifying code and all interpreter fallbacks.
  IOP and VU interpreters make eventual game execution hybrid even when EE
  functions are statically translated; the project manifest must declare this.
- [ ] Qualify IOP/IRX loading, SIF RPC/DMA, VU0/VU1, VIF/GIF and scheduler/IRQ
  behavior with original programs. Do not silently replace game logic with
  `ret0`, `ret1` or skipped wrappers.
- [ ] Implement GS GPU geometry rendering with correct texture/readback/transfer
  synchronization, automatic reported software fallback, required-GPU errors,
  current-monitor startup, drawable resize/high-DPI and native fullscreen.
- [ ] Qualify original input, SPU2 audio, filesystem/CD/DVD reads, MPEG and memory
  card save/reload behavior. No retail BIOS may be bundled in an output.
- [ ] Generate a standalone repository with pinned runtime/dependency identities,
  asset extraction, supported input hashes and honest execution reports. Build
  and execute it from a clean Windows/Linux checkout before enabling GUI export.
- [ ] Validate supplied DQVIII boot, modules, rendering, audio and saves. Final
  playthrough acceptance belongs to the user.

## Preserved work

Existing EE-GCC 2.96 matching, native Windows compiler hosts and exact ELF
reconstruction remain available. Their tests are separate from PC runtime
qualification. The exact GNUPro compiler-source investigation and whole-disc
repacking do not block this native-output milestone. [ico-pc](https://github.com/nathanialf/ico-pc)
is a game-specific product reference; its ICO bindings do not establish DQVIII
support. No original game assets, BIOS, SDK payloads or generated retail source
belong in this public PR.
