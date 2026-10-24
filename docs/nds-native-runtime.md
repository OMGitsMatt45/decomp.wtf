# DS native runtime integration

PR #29 now includes an additional experimental adapter that generates ARM9/ARM7
C++ and ships a native DS hardware runtime as source. It uses the original MIT
runtime/recompiler from [DQ9-Decomp](https://github.com/0bAndyWirus/DQ9-Decomp),
pinned at `b8fc609c20699ad5afe36922b7f2aa42436ec931` with archive SHA-256
`1c7d8cef88039252d8c1c250a64ad620d7f98cda0f42adb5b183bbfe11d45385`.
The runtime includes memory/TCM, IRQs, timers, DMA, 2D/3D graphics, DS audio,
buttons/touch, cartridge access and save devices. Its timings and hardware model
still have limits; reusing it does not establish another game's compatibility.

## Generate a repository

On the home screen, drop a DS ROM and choose **Native PC source project
(experimental)**. Select its ROM format and cartridge save chip, then generate.
This route bypasses console matching/compiler setup. It creates a fresh output
folder and reports its path. Existing DS reconstruction projects can use
**Export native PC project** on the Source tab. Existing output is preserved.
Both GUI and CLI use the same source generator and integrity checks.

```sh
uv run decomp pc nds-native original.nds output --experimental --input-format decrypted --save-type eeprom64k
```

Use `--input-format decrypted` only for a decrypted copy. `auto` uses the normal
DS decoder; `--arm7-bios PATH` supplies the private decoding input for encrypted
originals when needed. The application downloads the pinned MIT `dsr-sdk` and
DS analysis tool automatically. No matching console compiler is needed.

The exporter analyzes the ROM's functions, modes, overlays and autoloads, then
derives native thread-context bindings from decoded save/restore and IRQ behavior.
It rejects ambiguous or incomplete bindings and unsupported instruction sites.
The bindings are input-derived metadata, not a public database of game addresses.
Existing source-recovery projects and their matching work remain separate.

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
source is already included. `-DNDS_WITH_SDL=OFF` makes a headless-only build.

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

The original DS game supplies all required assets and audio. Mobile OBB data is
optional enhancement material in some existing ports, and is not used here.
BIOS and firmware are not linked into the runtime or copied into generated projects.
When an encrypted original needs secure-area decoding, the exported extraction
metadata contains the owner's decoded prefix. Standalone staging verifies the
original hash, applies that private patch and verifies the resulting asset hash;
it needs neither the BIOS nor decomp.wtf. The supplied original is preserved.

### Optional mobile remaster enhancements

Optional, owner-supplied mobile assets are a product requirement for Dragon
Quest IV, V and VI. DQIV Recompiled demonstrates this with replacement music
and sound effects from an Android OBB, and an in-game choice between mobile
and original DS sound. The DS-only build must remain complete without an OBB.

This adapter does not yet implement that replacement path. Each title needs
its own reviewed asset mapping and sound-event/loop/volume bindings; a shared
developer does not establish that the three archives have interchangeable
formats or track IDs. Add-ons must identify the supported game/revision and
asset identities, extract locally without shipping mobile data, and allow
switching back to DS audio. Validate missing, mismatched and disabled add-ons
alongside the enhanced path. Mobile remaster-mod archives need the same
checks as the original Android data. This enhancement follows the native
DS execution and save/reload milestones.

## Runtime corrections and qualification

The source-shipped runtime records decomp.wtf's changes in its patch document:

- Direct boot loads ARM7 bytes through the ARM7 bus, including private WRAM.
- ARM946 TCM mapping uses the distinct DTCM/ITCM enable bits correctly.
- Repeating short cartridge DMA services the full current READY block and its
  completion IRQ, while respecting block boundaries and disabled channels.

The emitter also distinguishes a signed negative-index guard from a switch's
upper bound. This prevents truncating a Thumb halfword jump table to its first
case. These changes contain no retail-specific addresses or bytes.

Original CC0 fixtures test ARM9/ARM7 communication, a real overlay-copy loader,
both rendered screens, nonzero DS PCM output, guest VBlank IRQs, button input,
SPI EEPROM reload, selective TCM mapping, repeated one-word card DMA, and signed
Thumb switch cases. Generated input identity uses streaming SHA-256, checked
against standard vectors and padding boundaries. The dedicated workflow installs
the pinned source dependency and tests the generated host on Windows and Linux.

DQV retail testing is ongoing. It exposed the short-DMA stall and a switch-table
coverage defect; both fixes have original regression cases. A correct save-chip
configuration is also required. Successful source generation, boot, rendering,
audio, menus, field/battle behavior and save/reload are separate checks. The
eventual full playthrough stays with the user. GUI availability is explicitly
experimental and does not establish retail compatibility. The clean standalone
DQV output also built and ran through name entry; advancing into new-game setup
exposed another invalid indirect call, under active investigation.
