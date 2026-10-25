# Experimental PS1 native PC projects

PS1 export produces a standalone C/C++ source repository and one executable for
the game's complete ordered disc set. It includes generated game C, the pinned
PSXRecomp hardware runtime, OpenGL geometry rendering, audio, keyboard/gamepad
input, CD access and persistent shared memory cards. It needs no matching-console
compiler, agent, retail BIOS or firmware. Bundled OpenBIOS is MIT-licensed.

PSXRecomp and its generated helpers use **PolyForm Noncommercial 1.0.0**.
The application and integration remain MIT. The generated repository includes
both licenses and OpenBIOS's license. This optional dependency is installed only
when exporting PS1; capability inspection and app setup do not download it.

## Generate

In the app, select PS1 and native PC output. Use a local CUE path with its data
and audio tracks alongside it; list additional discs in order, or choose an M3U
playlist. A single ISO/BIN/CHD/PS-X EXE can also be used. The Source tab exports
an existing imported game or combined disc set. Reviewed, hash-bound module
layouts are translated when exporting retained projects; unknown modules retain
the disclosed interpreter fallback. Original discs and prior source edits are
preserved. PS1 has no DS save-chip or screen-merger settings.

```sh
decomp pc psx-native /path/to/game.m3u /path/to/new-source --experimental
# Or list the actual discs, in order, before the new destination:
decomp pc psx-native disc1.cue disc2.cue /path/to/new-source --experimental --renderer opengl
decomp pc verify /path/to/new-source
```

The optional connected-agent tool `generate_pc_project` accepts `platform="psx"`
and ordered additional `disc_paths`. Generation does not start matching or agents.

## Build the standalone output

Install [Python 3.12+](https://www.python.org/downloads/),
[CMake 3.24+](https://cmake.org/download/) and a native C/C++ compiler.
On Windows, install [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
with Desktop development with C++. On Linux use GCC or Clang and the development
libraries listed in the generated README, including the
[SDL3 X11 dependencies](https://wiki.libsdl.org/SDL3/README-linux#build-dependencies).
These requirements apply to both PS1 export and building the output; the emitter
is built automatically from its pinned source during export.

From the generated repository:

```sh
python tools/extract_assets.py /path/to/game.m3u
cmake -S . -B build
cmake --build build --config Release --parallel 2
```

The standard-library asset helper verifies every ordered input and CUE track
before staging. Missing, changed or reordered media fails without replacing
existing assets or saves. Assets are excluded from Git. SDL3, libchdr and libwebp
download automatically during the documented build. No decomp.wtf installation
is required to build or run the exported project.

Run `build/ps1_pc` on Linux or `build/Release/ps1_pc.exe` with Visual Studio.
The initial window fits the active monitor; geometry rendering follows physical
drawable pixels when resizing or changing displays. F11 toggles native-monitor
fullscreen. F9/F10 cycle the actual inserted disc through the tray-change path,
when the game requests a change. Memory cards are shared under `saves/`.
Keyboard/gamepad configuration is recorded in `config.ini`.

`--renderer auto` tries OpenGL and reports software fallback; `--renderer opengl`
requires a working GPU context. `--renderer software` explicitly selects software.
`--resolution WIDTHxHEIGHT` chooses a starting size; it does not fix the render
resolution for later resizes. `--fullscreen` starts at native monitor resolution.
An export made with `--renderer opengl` also requires OpenGL by default at launch;
headless checks can explicitly override it with `--renderer software`.

## Execution model and evidence

The model is **hybrid**, not fully static recovery. Recognized original code runs
as generated C. Unresolved or changed code runs through the R3000 interpreter;
runtime guest-code compilation is disabled. Each static module validates its
own original bytes, so two discs or overlays sharing an address cannot select
the wrong native function merely because a particular disc is inserted.

Bounded checks support `--frames N --report result.json --capture frame.ppm`,
`--observe ADDRESS`, `--switch-disc FRAME:N` and `--resize FRAME:WIDTHxHEIGHT`.
Reports include the actual renderer/device, drawable/monitor dimensions,
fullscreen state, native and interpreted execution counts, module dispatches,
disc identity, audio and observed guest RAM. Manifest verification alone checks
source integrity and declarations; it does not certify gameplay.

The original two-disc qualification fixture checks native execution against
interpreted original bytes, CD payloads, real SPU output, memory-card save/reload
between discs, live tray changes, and correct dispatch at overlapping addresses.
Linux additionally exercises actual Mesa OpenGL geometry, adaptive resizing,
portrait and fullscreen, reported software fallback and explicit GPU failure.
Windows/Linux CI builds the exported source project from its pinned dependencies.
The smaller independent CPU probe retains its separate register/delay-slot checks.

Retail compatibility remains title-specific. DQVII is the first target; targeted
boot/module/save/disc checks and a full playthrough establish different evidence.
The user owns the eventual full playthrough. See the [runtime pins and integration
record](future/ps1-native.md). Source matching is separately paused in PR #26.
