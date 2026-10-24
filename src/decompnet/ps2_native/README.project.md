# PS2 native PC source project

This project contains generated game C++, a source-shipped PS2 runtime, SDL3
Vulkan geometry rendering, audio, keyboard/gamepad input, disc access and saves.
It requires your original input. No retail BIOS is required. The PS2 runtime
and graphics sources use GPL-3.0; bundled dependencies retain their licenses.
Compatibility is experimental. A successful export verifies source structure
and emission diagnostics; it does not certify a complete retail playthrough.

The EE game code is statically translated. Explicit SDK bindings appear separately
in pc-project.json. Unknown or changed EE code fails instead of silently skipping
it. The IOP and VU microprograms can use interpreters; no guest compiler runs during
play. Reviewed code maps are bound to the original input hash. This source is
editable native code, rather than recovery of the original source names/comments.

## Build and run

Install [Python 3.12+](https://www.python.org/downloads/),
[CMake 3.24+](https://cmake.org/download/) and an x86-64 C++20 compiler. Windows
uses [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/)
with Desktop development with C++. Linux uses GCC or Clang and desktop libraries:

```sh
sudo apt-get install build-essential pkg-config libx11-dev libxext-dev libxcursor-dev libxi-dev libxfixes-dev libxrandr-dev libxss-dev libxtst-dev libasound2-dev libgl-dev libavcodec-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev
python tools/extract_assets.py /path/to/original.iso
cmake -S . -B build
cmake --build build --config Release --target ps2_pc --parallel 2
```

CMake fetches checksum-pinned SDL3, raylib and shader compiler sources as needed;
Windows also downloads verified FFmpeg libraries automatically. A system
[Vulkan driver](https://www.vulkan.org/tools) must support SDL3 GPU. The Python
asset helper verifies your input before staging and preserves existing assets
and saves. Large archives remain in the disc image; only the boot program and
IOP modules are extracted.
Add --reference to the asset helper to retain the original disc at its current
absolute path without copying it. Keep that file available when running; saves
remain inside this source project. The default copies the disc for portability.
Raw CD sector formats select CD medium replies automatically. For a CD converted
to a 2048-byte ISO, set `disc_medium` to `cd` in its reviewed profile; otherwise
2048-byte inputs use DVD replies. The original image's sector/file data is retained.

Run build/ps2_pc or build/Release/ps2_pc.exe. F11 toggles native-monitor fullscreen.
The initial window follows the active display; resizing/moving it updates its
physical drawable and internal geometry scale, including HiDPI. Saves live under
saves; preserve them when updating the project. Default keyboard controls are
Z/X/A/S for face buttons, arrows for the direction pad, Enter for Start and
Backspace for Select; standard gamepads are detected by SDL.

Options include --renderer auto|vulkan|software, --resolution WIDTHxHEIGHT,
--fullscreen, --project PATH, --frames N, --seconds N, --report result.json,
--capture frame.ppm and --resize FRAME:WIDTHxHEIGHT. Explicit Vulkan fails if
unavailable. Automatic mode reports its software fallback. Reports expose guest
dispatch failures, disc reads, GPU draws, drawable dimensions and internal scale;
a blank boot or missing requested capture is not valid rendering evidence.
