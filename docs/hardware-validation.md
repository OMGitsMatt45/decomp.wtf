# Windows GPU validation

Run these commands from the repository folder containing `pyproject.toml` and
`tools`. They build original test programs and retain reports and logs. No retail
game or BIOS is needed. A fixture result qualifies its tested backend and device;
it does not certify a full game playthrough.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Visual Studio C++ Build Tools](https://visualstudio.microsoft.com/downloads/)
(Visual Studio 2022 or later). Select **Desktop development with C++** and
**C++ CMake tools for Windows**. The wrappers discover bundled CMake when it is
absent from PATH; a separate [CMake installation](https://cmake.org/download/)
also works. 3DS additionally needs [Rust 1.95+](https://www.rust-lang.org/tools/install)
with the MSVC toolchain. Use a current driver for your graphics device.

From PowerShell, install uv if needed:

```powershell
winget install --id astral-sh.uv --exact
```

Reopen PowerShell to refresh PATH. For a ZIP checkout, use File Explorer to find
the extracted directory containing `pyproject.toml`, type `powershell` into its
address bar, and run a command below.

## Commands

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-ps2-hardware.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-gba-hardware.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-3ds-hardware.ps1
```

Run one assessment at a time. Initial source verification and compilation can
take several minutes. Each wrapper chooses a fresh temporary output directory
and prints the path to `hardware-assessment.json`. Preserve that report and its
logs when reporting a result.

PS2 checks the standalone Vulkan pipeline, adaptive geometry, services and native
execution. GBA compares 18 OpenGL scenes and resized output. 3DS checks four
Vulkan scenes and the original two-screen desktop presentation. The reports
identify actual rendering devices. CPU, virtual or ambiguous devices do not
establish physical-GPU qualification.

The owner-provided Intel Iris Xe records identify exact tested revisions and
scope: [PS2](ps2-hardware-validation.json), [GBA](gba-hardware-validation.json),
[3DS](3ds-hardware-validation.json). Hosted CI performs its documented original
checks without claiming access to the owner's physical GPU.

## Common setup problems

- **`uv is not recognized`:** install uv and reopen the terminal. The wrappers
  also check standard user installation folders.
- **`No module named tools`, or `--locked` has no effect:** the terminal is
  outside the repository. Change to the directory containing `pyproject.toml`.
- **CMake is missing:** add Visual Studio's **C++ CMake tools for Windows**
  component, or install CMake separately. Having a C++ compiler alone does not
  imply that component is installed.
- **An interrupted check:** Ctrl+C leaves the run unqualified. Use a new output
  folder when retrying; earlier reports, logs and user work are preserved.
- **GPU setup failed:** inspect the saved log and the actual selected-device
  fields before interpreting a result. Update the device's driver as needed.

For a custom PS2 destination, keep the path short to leave room for Windows
compiler dependency paths:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\qualify-ps2-hardware.ps1 -Output "$env:TEMP\dg-test1"
```

See the [PS2 guide](future/ps2.md), [GBA guide](future/gba.md#test-a-windows-gpu)
and [3DS guide](3ds-native.md) for detailed qualification scope.
