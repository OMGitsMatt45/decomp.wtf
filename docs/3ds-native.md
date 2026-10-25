# Nintendo 3DS native source work

Status: **initial CPU source milestone; playable game output is not available**.
The goal remains an independent editable game C/C++ repository with a source
runtime, adaptive GPU rendering, dual-screen presentation, audio, controls and
saves, like the other console outputs. The DS runtime cannot supply the 3DS
ARM11 kernel, services and PICA200 GPU.

## What works now

- Read-only, bounded inspection of decrypted NCCH/CXI and NCSD/CCI/`.3ds` images.
  The loader checks partition and ExeFS ranges, executable segment mappings,
  BSS bounds, the `.code` checksum and bounded backwards LZSS decompression.
- ARM/Thumb/VFP C generation through MIT
  [3dsrecomp at cec1270](https://github.com/fearkov/3dsrecomp/tree/cec1270db38411f9c02d3f356fc3ed6c3f007424).
  Both the downloaded archive and extracted source have pinned SHA-256 values.
  A dependency-free adapter builds the emitter without fetching its optional
  emulator or Rust package dependencies. Original upstream sources are preserved.
- A separate `ctr-probe` export produces `game/`, `runtime/`, `assets/`, CMake,
  source/input identities and build instructions. Its generated C builds with
  the host C/C++ compiler; the exported project needs neither Rust nor decomp.wtf.
- Original CC0 ARM, Thumb-interworking and VFP fixtures execute natively and
  agree with independent Unicorn execution. Editing generated C changes the
  executable's result. BSS initialization, asset identity, read-only code,
  unknown targets/opcodes, unsupported SVCs and execution budgets are checked.
- The only implemented kernel call is `svcExitProcess`. The harness has no
  interpreter or JIT, and unsupported execution fails explicitly. It does not
  implement a kernel scheduler or claim CPU timing accuracy.

## Commands and prerequisites

From the repository root, inspect your decrypted executable:

```powershell
uv run --locked python -m decompnet.cli pc ctr-inspect "game.3ds"
```

Use the installed `decomp pc ctr-inspect` command instead if preferred. To export
an explicit CPU development project:

```powershell
decomp pc ctr-probe "game.3ds" "New 3DS source" --experimental
cmake -S "New 3DS source" -B "New 3DS source/build"
cmake --build "New 3DS source/build" --config Release
```

Required downloads that are not installed automatically:

- [Rust 1.88 or newer](https://www.rust-lang.org/tools/install), used to build
  the translator during export. Windows CI uses the MSVC Rust toolchain.
- [Visual Studio C++ tools](https://visualstudio.microsoft.com/downloads/) on
  Windows. Include **C++ CMake tools for Windows**, or install
  [CMake](https://cmake.org/download/) separately and put it on PATH. Linux needs
  a host C/C++ compiler and CMake.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for repository
  commands; an installed application can use `decomp` directly.

The pinned emitter sources download automatically. `DECOMP_3DS_SDK` can select
an existing **unmodified, pinned** source tree. `DECOMP_3DS_RUSTC` can select a
Rust compiler executable. No 3DS BIOS, system firmware, keys or title database
are required for this CPU milestone. Encrypted inputs fail with a decrypted-dump
message. This phase does not decrypt, install CIA files or relocate 3DSX homebrew.

For an original input with no retail data:

```powershell
uv run --locked python -m tools.ctr_fixture original.cxi --kind thumb
decomp pc ctr-probe original.cxi "Original 3DS source" --experimental
```

After building, run `build/Release/ctr_probe.exe assets 100000` on Visual Studio,
or `build/ctr_probe assets 100000` on Linux, from inside the generated project.
Exit status 0 means the original program reached ExitProcess, 1 means unsupported
execution or an integrity failure, and 2 means the instruction budget expired.
The JSON report explicitly disclaims graphics and retail qualification.

## Work needed for game output

1. Integrate a source-shipped kernel and service runtime: threads, synchronization,
   memory allocation, IPC, FS/RomFS and CRO loading/relocation. Keep executable
   identities and modified-code guards valid across module loads and updates.
2. Integrate PICA200 command/shader/texture handling and adaptive hardware
   rasterization. Support both screens at the current drawable size, resize,
   high DPI, active-monitor fullscreen and reported software compatibility mode.
   A framebuffer presented by OpenGL alone does not qualify as GPU rendering.
3. Add input/touch, audio/DSP services, persistent saves, title/update handling,
   failure reports and a desktop executable that includes its runtime sources.
4. Qualify original fixtures on Linux and Windows, then owner-supplied Pokémon
   and Dragon Quest revisions. Publish actual fallback and compatibility evidence.
   A successful probe or an upstream compatibility claim is not retail acceptance.

The MIT [Zakuro runtime](https://github.com/fearkov/zakuro) is a candidate for
the next stage because it implements the emitter ABI and already offers static
ports. It still needs independent pinning, integration, source packaging and
validation here; no installed emulator is substituted by this milestone.
`pc status --platform 3ds` therefore continues to report **no game backend**.
