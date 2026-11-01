# DS native runtime integration

PR #29 now includes an additional experimental adapter that generates ARM9/ARM7
C++ and ships a native DS hardware runtime as source. It uses the original MIT
runtime/recompiler from [DQ9-Remastered](https://github.com/dq9-remastered/DQ9-Remastered),
pinned at `b8fc609c20699ad5afe36922b7f2aa42436ec931` with archive SHA-256
`7a556630652e1173778b3e65999199dc8e77f914220a1430d2d67fc220d3ee08`.
The repository moved after 0.20.0; its canonical archive has a new root name and
checksum. All 389 file blobs match the same pinned commit (with the archive's
Windows text line endings normalized for the Git comparison).
The runtime includes memory/TCM, IRQs, timers, DMA, 2D/3D graphics, DS audio,
buttons/touch, cartridge access and save devices. Its timings and hardware model
still have limits; reusing it does not establish another game's compatibility.

## Generate a repository

On the home screen, drop a DS ROM and choose **Native PC source project
(experimental)**. Select its ROM format and cartridge save chip, then generate.
Choose the renderer used by the generated project. Both original screens remain
visible; combined-camera enhancements belong in game-specific output work.
This route bypasses console matching/compiler setup. It creates a fresh output
folder and reports its path. Existing DS reconstruction projects can use
**Export native PC project** on the Source tab. Existing output is preserved.
The GUI, CLI and connected-agent tools use the same source generator and
integrity checks.

```sh
uv run decomp pc nds-native original.nds output --experimental --input-format decrypted --save-type eeprom64k
```

Add `--renderer opengl` to require GPU rendering. The GUI, CLI and optional
connected-agent tools accept `renderer` (`auto`, `opengl`, `software`). Both
original screens remain visible; combined cameras are an output customization.
Invalid renderer values fail before dependency installation or publication.

An optional agent connected with `decomp mcp` can call
`generate_pc_project(path, own_copy=true, ds_input_format="decrypted", save_type="eeprom64k")`.
This generates directly from the ROM without creating a matching project or
starting helpers. For an already-open DS reconstruction, use
`export_project(format="pc", save_type="eeprom64k")`; its default remains a
matching console export. Long-running jobs return an ID for `import_status`.
The tools report source generation separately from host/gameplay acceptance.

Use `--input-format decrypted` only for a decrypted copy. `auto` uses the normal
DS decoder; `--arm7-bios PATH` supplies the private decoding input for encrypted
originals when needed. The application downloads the pinned MIT `dsr-sdk` and
DS analysis tool automatically. No matching console compiler is needed.

The exporter analyzes the ROM's functions, modes, overlays and autoloads, then
derives native thread-context bindings from decoded save/restore and IRQ behavior.
It rejects ambiguous or incomplete bindings and unsupported instruction sites.
The bindings are input-derived metadata, not a public database of game addresses.
Existing source-recovery projects and their matching work remain separate.

The callback recovery pass also follows direct call relocations that identify
exactly one destination module, checking the actual calling instruction and
ARM/Thumb exchange. This recovers routines mislabeled as data even when the
only caller lives in resident code or another overlay. Ambiguous overlay
destinations and unreferenced prologues do not seed recovery. The recovery
metadata records pointer and qualified-call evidence separately.
PC-relative ARM stores are accepted only when their destinations can be
retained as initialized data, disjoint from decoded instructions. Recovered
regions exclude literal data from overlay identity hashes, allowing callbacks
to update return-address slots without losing their compiled dispatch entry.
Referenced-callback recovery and strict code-gap discovery alternate until
neither adds a function. Newly recovered wrappers can bound previously rejected
gaps; the later scan retains existing dispatch regions and records additional
gap evidence separately.
For DS Protect modules, decoded toolkit metadata supplies the protected ARM
function boundaries and known literal pools. These replace overlapping gap
guesses before callback recovery. Each protected routine has its own dispatch
identity so another routine being encrypted, decrypted or updating a pool does
not invalidate the active entry. Boundary alignment, module extent and overlap
checks reject inconsistent metadata.

Generated players include an F1 settings menu and optional ROM-bound data
cheat catalogs. See [DS settings and data cheats](nds-cheats.md).

The original fixture route accepts `--profile reviewed.json`; that route requires
the original loader code rather than the small backend's native overlay hook.
Its optional RAM checkpoint belongs to `nds-generate`; `nds-native` uses the
cartridge save device. The fixture is independent of SDK layout inference.

## What the project contains

- `game/arm9/` and `game/arm7/`: generated C++, indirect dispatch and function tables.
- `game/recovery.json`: reviewed module/function/mode facts and decoded hashes.
- `native/dsr/`: runtime source, upstream MIT license, attribution and our patch record.
- `native/main.cpp`: generic window/input/audio host, headless runner and diagnostics.
- `native/profile.hpp`: exact input identity, cartridge save type and derived context bindings.
- `tools/extract_assets.py`, CMake, README and `pc-project.json` with file hashes.

The generated repository builds independently of decomp.wtf. Python 3.9+ stages
assets; CMake 3.20+ and a C++20 compiler build the project on x86-64 Windows/Linux.
Host-tool download links are in the main README and generated README. The default
window build downloads and verifies SDL2 2.32.10 automatically. The DS runtime
source is already included. Linux desktop builds also need the distribution's
X11/Xext and OpenGL/EGL development packages before SDL configuration; see
[manual host dependencies](../README.md#downloads-you-install-yourself).
`-DNDS_WITH_SDL=OFF` makes a headless-only build.

```sh
python tools/extract_assets.py /path/to/original.nds
cmake -S . -B build
cmake --build build --config Release --parallel 2
ctest --test-dir build -C Release --output-on-failure
```

Run `build/ds_pc --assets assets` on Linux, or
`build/Release/ds_pc.exe --assets assets` with Visual Studio. The README lists
keyboard/touch controls and save locations. `--headless --frames N` bounds a
scripted run; `--capture DIR`, `--audio-pcm FILE`, `--input-script FILE`,
`--diagnostics` and `--dump-memory DIR` support private compatibility testing.
Do not publish retail-derived sources, assets, memory captures or game builds.

Generated games use the computer's current local date/time by default, including
after restarting a saved game. For reproducible tests, pass
`--rtc-start 1704067200` to start at 2024-01-01 00:00:00 UTC and advance the clock
with emulated time. The accepted Unix timestamp range is 2000 through 2099 UTC.
The JSON result records `rtc.mode` (`local` or `fixed-utc`) and `rtc.start_unix`
(`null` for the local clock). Fixed time is an explicit testing option; normal
launches retain the local clock for calendar and daily events.

## Enhanced GPU rendering

The original OpenGL 3.3 host redraws transformed game geometry at up to 12 times
the DS resolution (3072x2304 per 3D scene), limited by the driver's maximum
texture size. Enhancement is enabled by default without a game-menu switch.
A mip pyramid averages the high-resolution image to the actual drawable size
for antialiasing, including high-DPI scaling. The initial window size comes
from the active monitor's usable area. Resizing or moving between monitors
updates the render size every frame; no output resolution is hardcoded.
F11 or `--fullscreen` uses the current monitor's native resolution.
`--resolution WIDTHxHEIGHT` optionally sets an initial window size and does not
lock rendering to it. SDL loads OpenGL entry points; users need their graphics
driver, not a separate graphics SDK. `--renderer auto` reports a software
fallback when OpenGL is unavailable; `opengl` requires a working context.

The runtime captures an owned geometry/texture/mask snapshot at the actual 3D
render boundary. The host latches it before the following DS frame, matching
the 3D engine's one-frame pipeline. GPU pixels replace the eligible 3D part of
the DS composition. Captured VRAM images retain the serial and source coordinates of the
completed 3D raster that produced each unmodified pixel. The host retains those
owned scenes while VRAM or an LCD references them, renders each to a high-resolution
GPU target, and replays affine source mappings without replacing UI pixels.
CPU/DMA writes, genuine 2D blends, brightness changes and ambiguous overlapping
banks invalidate that provenance. Unknown or guarded effects retain native pixels; this path draws geometry rather than only scaling a framebuffer.

The two LCDs retain their native aspect ratios. Touch maps only to the displayed
lower LCD. Menus, 2D-only games and guarded effects keep their original output.
GPU passes implement fog after composition, polygon-ID/depth edge marking,
shadow masks, depth-equal overlays and per-ID translucent blending. Pixel state
is packed losslessly into an RG32F target; feedback copies cover only each
polygon's clipped bounds and retired framebuffer storage is reused. Clear-image
mode and geometry overflow retain complete native output. Original fonts,
2D sprites and pre-rendered video keep their source detail. Camera/culling/UI
enhancements can be made later in the exported game repository.

Windows executables export NVIDIA Optimus and AMD high-performance GPU requests;
system graphics preferences can override them. The renderer reports the GPU
actually selected, rather than inferring it from the installed adapters. The
12x path needs GPU performance qualification on the target machine.

Original fixtures qualify raw geometry clipped to the LCD, actual GL draw
calls, texture modulation, UI retention, touch
mapping, drawable resizing and fallback, plus final-pixel checks for fog,
alpha-only fog, fog/translucency ordering, outlines, shadows, self-shadow
exclusion, depth-equal overlays and supersampled edge coverage.
Another original ARM9/ARM7 program
submits 3D geometry through guest I/O and validates the complete generated-host
path against headless frame/tick/screen results. Linux qualification executes
OpenGL through Mesa; cloud testing does not measure physical graphics-card
performance. Windows qualification builds the same host and exercises software
presentation. `--capture` includes `display.ppm` at the actual drawable size;
JSON reports the renderer, device, dimensions, enhancement state, internal scale, both LCDs, draw count and the
number of native LCD texels actually replayed from captured 3D in the last frame.

The original DS game supplies all required assets and audio. Mobile OBB data is
optional enhancement material in some existing ports, and is not used here.
BIOS and firmware are not linked into the runtime or copied into generated projects.
When an encrypted original needs secure-area decoding, the exported extraction
metadata contains the owner's decoded prefix. Standalone staging verifies the
original hash, applies that private patch and verifies the resulting asset hash;
it needs neither the BIOS nor decomp.wtf. The supplied original is preserved.

### Optional mobile remaster enhancements

Optional, owner-supplied mobile assets are deferred to later game-specific
enhancement work for Dragon Quest IV, V and VI. DQIV Recompiled demonstrates replacement music
and sound effects from an Android OBB, and an in-game choice between mobile
and original DS sound. The DS-only build must remain complete without an OBB.

This adapter does not yet implement that replacement path. Each title needs
its own reviewed asset mapping and sound-event/loop/volume bindings; a shared
developer does not establish that the three archives have interchangeable
formats or track IDs. Add-ons must identify the supported game/revision and
asset identities, extract locally without shipping mobile data, and allow
switching back to DS audio. Validate missing, mismatched and disabled add-ons
alongside the enhanced path. Mobile remaster-mod archives need the same
checks as the original Android data. These extras do not block the common DS
output milestone; the current scope includes native output, GPU rendering and
two-screen presentation.

The user's DQIV reference is the [Mobile Remaster thread](https://www.romhacking.net/forum/index.php?topic=34365.0).
The author's [Nexus listing](https://www.nexusmods.com/dragonquest4/mods/1)
describes visual upgrades and orchestral music and points back to that thread
for current project details; the listing itself is marked out of date. This
identifies the intended enhancement project, not a tested archive format or
compatible asset hash. DQV and DQVI can instead use optional stock mobile
assets; a remaster mod is not required. Their official mobile-release pages are
[DQV](https://www.jp.square-enix.com/dqsp/dq5/en/) and
[DQVI](https://www.jp.square-enix.com/dqsp/dq6/en/). Archive package/version,
content hashes and per-title mappings still need validation against local
owner-supplied files; a download-page label alone does not qualify an archive.

## Runtime corrections and qualification

The source-shipped runtime records decomp.wtf's changes in its patch document:

- Direct boot loads ARM7 bytes through the ARM7 bus, including private WRAM.
- ARM946 TCM mapping uses the distinct DTCM/ITCM enable bits correctly.
- Repeating one-word cartridge DMA services the full current READY block and its
  completion IRQ, while respecting block boundaries and disabled channels.
  The latched count selects this path; other programmed block sizes retain the
  pinned runtime's notification/rearm behavior and still need further hardware
  qualification.

The emitter also distinguishes a signed negative-index guard from a switch's
upper bound. This prevents truncating a Thumb halfword jump table to its first
case. These changes contain no retail-specific addresses or bytes.
Shared Thumb return epilogues reached with BL consume the caller's saved frame;
generated code returns to the outer caller instead of falling into another case.
Halfword switch analysis also handles more than 256 entries, bounded by the
image, function and table/code boundaries (with a 4096-entry ceiling).

Original CC0 fixtures test ARM9/ARM7 communication, a real overlay-copy loader,
both rendered screens, nonzero DS PCM output, guest VBlank IRQs, button input,
SPI EEPROM reload, selective TCM mapping, repeated one-word card DMA, and signed
Thumb switch cases.
Shared-return and 300-case original fixtures cover the additional compiler
patterns. Cartridge bytes are committed atomically during play and on exit;
an interrupted-process test verifies that prior writes reload successfully.
Generated input identity uses streaming SHA-256, checked
against standard vectors and padding boundaries. The dedicated workflow installs
the pinned source dependency and tests the generated host on Windows and Linux.

DQV retail smoke testing exposed the short-DMA stall, switch-table
coverage defects and a shared-epilogue control-flow defect; all fixes have
original regression cases. A correct save-chip
configuration is also required. Successful source generation, boot, rendering,
audio, menus, field/battle behavior and save/reload are separate checks. The
eventual full playthrough stays with the user. GUI availability is explicitly
experimental and does not establish retail compatibility. The clean standalone
DQV output also built and ran through name entry. The shared-epilogue and large
switch fixes then allowed the native build to enter the opening castle scene,
with rendered scenery and characters matching the reference scene. Continuing
from the cartridge save lists the saved name, level and prologue and resumes
the scene after a restart. A 30,000-frame run reaches the ship cabin; directional
input moves the player and the field and Misc menus open. A fresh standalone
repository generated from the ROM, without a prior source project, built and
reproduced the same 22,400-frame run and screen hashes. An independent emulator
also loaded the native build's raw save and resumed the prologue. Combat,
later retail saves and playthrough validation are owner-run acceptance checks.
Implementation checks use automated fixtures and targeted defect reproductions.

Customized game outputs can also observe native 2D foreground planes through
`screen_top_foreground()` and `screen_bottom_foreground()`. These are borrowed
premultiplied ARGB8 values with a known flag (bit 32) and unsupported-composition
flag (bit 33). Captured 3D and its clear background are transparent in this plane;
native text/sprites and DS alpha darkening remain separate. CPU writes invalidate
physical capture metadata. Tracking remains opt-in and changes no DS pixels,
registers, or timing. The standard generated player keeps its two-LCD layout;
projection changes and layout choices belong to individual game adaptations.
# Native SDK callbacks from a customized host

Generated projects expose `Machine::post_guest_work(cpu, callback)` for native
extensions that must invoke translated SDK code, such as streaming audio.
Enqueue work from the machine's owning host thread. It runs on the selected
CPU's guest fiber at a user/system checkpoint with IRQs enabled, after pending
interrupt delivery. It can yield through SDK calls without reentering another
queued callback. Registers and flags are restored; memory writes and charged
execution time remain. The queue accepts 64 pending callbacks per CPU, clears
on machine reset, and reports callback exceptions on the host stack.

Captured objects must remain alive until their callback runs or reset cancels
it. Callbacks must obey the guest SDK's calling and locking rules; this API
does not provide a new guest thread or permission to invoke SDK code from an
SDL audio thread.
