# PS2 native PC output

Implementation work continues in [PR #5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5),
based on main after the DS and PS1 native output merges. The target is one
standalone CMake source project with generated EE game code, source-shipped
runtime, locally extracted assets and adaptive GPU rendering. PS2 has one
screen. DQVIII is the first intended retail validation input; it has not yet
been supplied for this milestone.

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

These checks qualify CPU translation only. The assessment host rejects changed
fixture bytes before dispatch; upstream's generated table does not itself
guard newly loaded overlays. Missing function dispatch is configured to stop.
No graphics, audio, IOP, vector unit, save, gameplay or general retail claim
follows from a CPU result. The app does not register a PS2 PC backend yet.
Logs, generated sources, expected/actual state and the candidate license remain
in the assessment directory, including on failure.

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

## Runtime work required before game output

The candidate supplies an EE runtime, R3000A IRX execution with IOP kernel/HLE
services, VU interpreters, GS, audio and virtual filesystem code. Those are
reuse candidates whose behavior needs original execution tests. Its current
`GSRasterBackend` implementation is `GSCpuBackend`: CPU rasterization followed
by host presentation. A GPU window displaying a software framebuffer does not
satisfy our [GPU geometry contract](../pc-output.md#shared-gpu-presentation-standard).

- [ ] Qualify original EE translation through native Windows and Linux builds.
- [ ] Add per-module original-byte guards and explicit handling of overlays,
  unresolved dispatch, self-modifying code and all interpreter fallbacks.
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
