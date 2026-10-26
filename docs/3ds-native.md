# Nintendo 3DS native source work

Status: **experimental standalone native output; full retail gameplay is not qualified**.
The goal remains an independent editable game C/C++ repository with a source
runtime, adaptive GPU rendering, dual-screen presentation, audio, controls and
saves. The application, connected-agent tools and `pc ctr-native` share the same
experimental game backend. `pc status --platform 3ds` reports it without
installing optional sources. CPU/service probes remain available for diagnosis.

## Implemented foundation

- Bounded read-only inspection of decrypted NCCH/CXI and NCSD/CCI/`.3ds` images:
  partition/ExeFS ranges, executable mappings, BSS, code checksums and backwards
  LZSS decompression, including final data-page padding. An independently
  compressed original executable checks every instruction/data byte against
  both pinned decoders and the runtime's loaded memory, as well as native
  execution against Unicorn.
- ARM/Thumb/VFP C generation through MIT
  [3dsrecomp at cec1270](https://github.com/fearkov/3dsrecomp/tree/cec1270db38411f9c02d3f356fc3ed6c3f007424).
  Data/rodata callback pointers, including contiguous self-relative callback
  tables, provide additional discovery roots. An original relative-table/Thumb
  fixture executes from native C and agrees with Unicorn. Archive and
  source SHA-256 pins are checked before building the dependency-free translator.
- `ctr-probe` exports a small independent C/C++ CPU harness. It needs no Rust
  after export and implements ExitProcess only. Original ARM, Thumb, VFP, BSS
  and data-table callback fixtures execute natively. Source edits change the
  result; malformed inputs, unknown instructions/targets, read-only memory,
  modified assets and instruction budgets are checked.
- `ctr-runtime` exports generated C plus a pinned MIT
  [Zakuro source runtime at e174910](https://github.com/fearkov/zakuro/tree/e174910de5e7285581b153cbce05543efb135cd5),
  matching recompiler ABI, independent host, CMake and locked Rust dependencies.
  It does not depend on an installed emulator or decomp.wtf after export.
- Bounded RomFS traversal extracts CRO/CRS modules under generated filenames.
  Their exports, imports and relocation roots feed C generation, including
  static-CRS exports from the main executable. Original ARM/Thumb module tests
  execute at two load addresses without interpretation, reload after a clean
  copy, reject changed code and remove stale entries on unload. Read-only asset
  aliases are allowed; conflicting module contents with one name fail explicitly.
  Directory links, UTF-16 names, parent relationships and data ranges are checked.
  Whole-input and module SHA identities are recorded; IVFC hash-tree verification
  is not claimed by the bounded directory walker.
- An original ARM11 program exercises real memory allocation, event signaling
  and waits, srv:/configuration IPC and an asynchronous ExeFS read. Its expected
  result takes 168 native instructions with zero interpreted instructions.
  One-instruction budgets resume without interpretation. Missing dispatch
  targets and inline unsupported instructions both stop in strict mode;
  compatibility fallback requires an explicit option and is counted separately.
  Unknown SVCs/IPC commands stop with an unsupported-service report.
- Vulkan PICA geometry scenes render original triangles at changing resolutions,
  compare independent software PICA results and preserve dirty guest framebuffer
  data across renderer resize. Software Vulkan is valid development evidence,
  not physical GPU qualification.
- The optional desktop host presents both pictures with adaptive geometry render
  scale, window resize/high DPI, monitor fullscreen and keyboard/touch input.
  Both original LCDs remain visible with their native aspects and touch mapping.
  F11 changes fullscreen. No fixed display resolution or forced 16:9 shape is
  assumed. Game-specific camera merging belongs in the exported repository.
- The desktop host queues DSP samples to the pinned resampling/audio sink and
  merges standard controllers with keyboard/touch input. It reports missing
  devices and supports `--mute`. Original queue/resampling and controller merge
  checks run on both hosts; a nonzero original tone is consumed by a virtual
  Linux audio callback. Physical audio/controller acceptance remains separate.
- An original translated ARM save program creates its archive only after the
  exact not-formatted result, then writes a counter and reads/increments it
  across separate launches. Existing sibling files survive; a corrupt counter
  fails without formatting or overwriting them. `--data DIRECTORY` keeps the
  runtime's title-isolated saves under `DIRECTORY/user/savedata/TITLE_ID`.
  This qualifies the original persistence path, not retail save formats.
- The runtime starts the guest clock at the host's local time and advances it
  with guest ticks. `--clock-ms N` explicitly selects a deterministic replay
  clock in milliseconds since 1900. Execution reports include the clock and
  fault PC/LR/mode to help diagnose missing native targets.
- Bounded headless runs accept up to ten billion cycles for startup validation.
  `--capture-guest-screens NEW_DIRECTORY` writes native top/bottom RGB PPMs and
  records their hashes; it preserves existing directories. GPU draw/transfer/
  fill counts and the actual Vulkan device name are reported independently of
  retail or physical-device qualification. The desktop starts maximized to its
  monitor and continues adapting to drawable resize/high DPI.
- Runtime reports can feed observed main-executable entry points into a new
  export with repeatable `--feedback REPORT.json` options. Reports must match
  the exact original image SHA-256. Targets, report sizes and entry counts are
  bounded; Thumb mode is preserved. Explicit compatibility runs collect missing
  region entries and retain their interpreted-instruction counts. Their results
  are discovery hints; the new output still defaults to strict execution and
  must be retested without interpretation. Relocated-module feedback and
  unsupported inline instructions need separate work.
- An empty offline StreetPass read returns CECD's real NoData result and zero
  bytes, preserving the caller's mapped buffer. Directory reads, invalid sizes
  and buffer permissions return errors. StreetPass mailbox writes and wireless
  exchange remain unimplemented; no received messages are fabricated.

## Commands and downloads

From the repository root:

```powershell
uv run --locked python -m decompnet.cli pc ctr-inspect "game.3ds"
uv run --locked python -m decompnet.cli pc ctr-native "game.3ds" "New 3DS source" --experimental
cmake -S "New 3DS source" -B "New 3DS source/build"
cmake --build "New 3DS source/build" --config Release
```

The installed `decomp pc` command also works. Inside the exported directory:

```powershell
.\build\host\debug\ctr_runtime.exe "PATH_TO_ORIGINAL_IMAGE" --window
```

On Linux use `build/host/debug/ctr_runtime`. For a bounded headless run, replace
`--window` with `--cycles 1000000`. Add `--gpu` for headless
Vulkan geometry. CMake defaults to the desktop build; `-DCTR_DESKTOP=OFF` omits
window dependencies. `-DCTR_CARGO_PROFILE=release` selects an optimized Rust
build and puts the executable under `build/host/release/`.

Save the execution report and use it when creating a new source directory:

```powershell
.\build\host\debug\ctr_runtime.exe "PATH_TO_ORIGINAL_IMAGE" --cycles 50000000 | Set-Content -Encoding utf8 coverage.json
uv run --locked python -m decompnet.cli pc ctr-runtime "PATH_TO_ORIGINAL_IMAGE" "Next 3DS source" --experimental --feedback coverage.json
```

The first command can stop at a missing target and still write a useful report.
`--allow-interpreter` is an explicit diagnostic option for collecting further
entries. Its interpreted execution is recorded and does not qualify a native
port. Export to a new directory so existing source edits remain available.

Downloads not installed automatically:

- [Rust 1.95+](https://www.rust-lang.org/tools/install) for source runtime builds;
  the smaller `ctr-probe` only needs Rust 1.88+ during export. Use MSVC Rust on
  Windows.
- [Visual Studio C++ tools](https://visualstudio.microsoft.com/downloads/).
  Include **C++ CMake tools for Windows**, or install
  [CMake](https://cmake.org/download/) separately. Linux needs a host C/C++
  compiler, CMake, pkg-config, ALSA/libudev development packages and X11 libraries.
  Ubuntu/Debian package names include `pkg-config`, `libasound2-dev` and
  `libudev-dev`; see the main README download links.
- A Vulkan-capable graphics driver from
  [Intel](https://www.intel.com/content/www/us/en/download-center/home.html),
  [AMD](https://www.amd.com/en/support/download/drivers.html) or
  [NVIDIA](https://www.nvidia.com/en-us/drivers/), or the system's Mesa packages
  on Linux. The Vulkan SDK is not required by this Rust host.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for repository
  commands; an installed application can use `decomp` directly.

Pinned sources and locked build crates download automatically. `DECOMP_3DS_SDK`
and `DECOMP_3DS_RUNTIME_SDK` select existing **unmodified, pinned** source trees;
`DECOMP_3DS_RUSTC` selects the export compiler. Integration changes apply to the
exported copy, preserving the immutable source caches and owner edits.

For a non-retail input:

```powershell
uv run --locked python -m tools.ctr_fixture original.cxi --kind services
uv run --locked python -m decompnet.cli pc ctr-runtime original.cxi "Original 3DS source" --experimental
```

The original image is bound to its full SHA-256 at launch. No BIOS, boot ROM,
system firmware, keys or title database is needed by these original fixtures.
Encrypted inputs fail with a decrypted-dump message. CIA installation and 3DSX
relocation are not implemented by this importer. Some retail services can need
additional owner-provided files; no system/game data is downloaded automatically.

## Bounded retail validation

An owner-supplied decrypted DQVII USA image was exported through the normal
standalone generator, without a game profile, feedback file or manually supplied
entry addresses. The generated C/runtime source was built independently and ran
for 10 billion guest cycles (2,231 frames) to the title screen. It executed
662,650,004 native instructions, zero interpreted instructions, and reported no
missing native targets, unsupported SVCs or unsupported service commands. The
captured original LCD pixels match the independently interpreted reference.
A separate Vulkan run reached the same title with the same native counts and no
fallback, using cloud llvmpipe. The software image comparison is exact; rasterizer
output is assessed separately. These bounded debug C builds do not qualify
release performance, physical GPUs, later gameplay, sound or saves.

General fixes discovered by this check include ARM-to-Thumb linker veneers,
Thumb position-independent callback discovery, idle scheduling at vertical blank,
and fresh GSP client handles after graphics reinitialization. Original fixtures
cover these patterns independently of the retail image. The original runtime
suite also passes Vulkan geometry, window resizing, save/relaunch and null-device
audio. Physical GPU acceptance uses the command below.

## Local graphics qualification

From a downloaded checkout, Windows PowerShell can run this script from any
current directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\qualify-3ds-hardware.ps1"
```

Use the script's full path when outside the checkout. It discovers the Visual
Studio CMake component and an installed uv/Rust toolchain. Rust 1.95+ with MSVC
is required; the download links above also apply to this command. `-CheckTools`
checks prerequisites without building. No game, boot ROM or firmware is used.

The assessment builds an original native loop, renders independent PICA geometry
at changing scales, and presents both original LCDs in a resizable window. Physical
qualification requires each actual Vulkan device name to match an integrated or
discrete device in the driver inventory. A software renderer cannot pass as
physical hardware. Results and command logs are retained in the printed output
directory. This validates the original graphics path, not retail gameplay,
physical audio or controller behavior.

The owner's [Windows 11 / Intel Iris Xe result](3ds-hardware-validation.json)
passed on 2026-10-26 with source integrity verified. All four Vulkan geometry
scenes passed, the framebuffer was preserved, and resizing exercised scales
1, 2, 3 and 1. The stacked two-screen window presented at 1920×991 and scale 3;
its original native program executed 13,443,408 instructions with no interpreter
use, missed native targets or unsupported services/SVCs. Actual scene/window
device names matched the integrated Vulkan device inventory. This owner-submitted
result qualifies that original graphics fixture on this GPU/driver combination;
it does not qualify retail gameplay, physical audio or controllers.

Linux developers with a display can run `python -m tools.qualify_ctr_hardware
NEW_DIRECTORY --allow-software`; this explicit comparison never qualifies a
software device as physical. Standard repository commands use `uv run --locked
--group dev --python 3.12 python` in place of `python`.

## Remaining game-output work

1. Broaden service-driven CRO/CRS load/import/relocation and executable-data
   coverage beyond the original placement/provenance fixtures. Original module
   success does not establish complete translated retail module coverage.
2. Broaden texture/effect coverage and physical GPU/driver coverage beyond the
   qualified Windows/Iris Xe original fixture using the local command. Both
   original screens remain visible; continuous
   camera/UI changes belong in each generated game repository.
3. Qualify retail DSP/audio, physical controllers and retail game saves.
   Host audio/controller integration and original signal/input fixtures are
   implemented, and an original native save/relaunch fixture passes; those do
   not establish correct sound or saves in every title.
4. Add title/update integration, relocated-module feedback and owner-supplied Pokémon
   and Dragon Quest retail acceptance. Interpreter use must remain explicit in
   both the project manifest and execution reports. A passing fixture, bounded
   run or upstream compatibility claim does not establish a playable retail port.
