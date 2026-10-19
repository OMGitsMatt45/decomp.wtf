# Running decomp.wtf natively on Windows

This fork runs the app and available compilers directly as Windows programs. The default installer does not
install WSL, enable virtualization, create a Linux distribution, or require administrator access.

## Install

Use Windows 10 or Windows 11 on a 64-bit Intel or AMD PC. Internet access is needed for the first setup.

1. Download [this fork’s source ZIP](https://github.com/OMGitsMatt45/decomp.wtf/archive/refs/heads/main.zip).
2. Extract the ZIP to a local folder. Open the extracted folder containing `windows.cmd`.
3. Double-click **`windows.cmd`**. Setup installs uv, a managed Python 3.12, the app and its default native tools.
4. Open **Demo Quest 64** from the home screen to check importing and compilation.

Or run the native installer from PowerShell:

```powershell
irm https://raw.githubusercontent.com/OMGitsMatt45/decomp.wtf/main/site/public/install.ps1 | iex
```

From a source checkout, the equivalent is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\site\public\install.ps1
```

Python and Git do not need to be installed separately. Agent CLIs may need their own prerequisites, such as
Node.js; the app shows which agents are available. The original `decomp.wtf` website still serves the archived
upstream installer; use this fork’s links above for native Windows support.

## Open it again

Use **decomp.wtf** in the Start menu or its desktop shortcut, or run `decomp` in a new PowerShell window.
The shortcuts start a minimized terminal window; closing that window stops the app. `decomp stop` also stops it.
If the browser does not open, `decomp url` prints its address.

Projects are stored in `%USERPROFILE%\Decomp` (usually `C:\Users\your-name\Decomp`). File selection,
drag-and-drop and paths such as `C:\Games\My Game.iso` all use ordinary Windows files.

Connect an installed Windows agent CLI with:

```powershell
decomp connect
```

Helpers launched by the app now run on Windows too. Sign them in from a normal Windows terminal using the
command displayed in **Agents & models**. Local model servers on Windows use the normal `127.0.0.1` addresses.

## Compilers and tools

The app lists native availability in **Compilers & tools**. It downloads Windows builds and verifies their
pinned SHA-256 checksums. A compiler with no native build is marked unavailable; setup does not start WSL for it.
IDO, CodeWarrior and CodeWarrior for DS are proprietary and keep their existing explicit installation step.

| Toolchain | Native Windows status |
| --- | --- |
| KMC GCC 2.7.2 / N64 | C++ host port, including the original binutils 2.6 |
| PlayStation GCC 2.7.2 | Native C/C++ source port, including the original binutils 2.6 |
| PlayStation GCC 2.8.1 | Native original C/C++ frontends with pinned compatible MIPS binutils |
| agbcc / Game Boy Advance | C compiler plus a restored GCC 2.95.3 C++ frontend using the agbcc Thumb backend |
| IDO 5.3 / 7.1 | Original statically recompiled SGI programs with bundled MSYS runtime; 7.1 includes a Windows host-memory fix; explicit license acceptance required |
| CodeWarrior for GameCube/Wii/DS | Existing upstream Windows builds; explicit license acceptance required |
| objdiff, decomp-toolkit, DS toolkit, MIPS/PPC/ARM binutils | Existing upstream Windows builds |
| EE-GCC 2.96 | No native build in this release; marked unavailable |

EE-GCC 2.96 C++ is supported on Linux with the original `2.96-ee-001003-1` frontend. Its archive
contains Linux i386 programs only, and no verified matching source/native Windows binary was found
for a Windows port. Public EE 2.9 and Windows SN 2.95 packages are different compilers.
See [PS2 C++ support and concrete alternatives](ps2-cpp.md). The installer does not
substitute another compiler version or silently enable WSL for it. Binary packages, corresponding source and
rebuild recipes are available in the [compiler assets branch](https://github.com/OMGitsMatt45/decomp.wtf/tree/native-toolchains-v1/toolchains/windows/v1).

N64 ROM analysis now runs in a bundled C++17 library. The Windows KMC GCC/binutils host implementation
is ported to GNU C++98, with all 195 project translation units built by G++. N64 projects using KMC now generate and export `.cpp` sources and compile them with the period C++ frontend.
The compiler archive includes a source/object build inventory; the corresponding source archive contains
the generated C++ implementation, original GPL source and rebuild recipes on the
[N64 C++ assets branch](https://github.com/OMGitsMatt45/decomp.wtf/tree/n64-game-cpp-assets/toolchains/windows/v1).

The fork’s compiler ports preserve the original target compiler. Updating the host build to Windows does not
replace a period compiler with a modern compiler. The native integration checks compare generated code and
relocations with the Linux compiler and require byte-exact matching on the bundled demo.

## Updates and removal

Close the app, then run `windows.cmd` or the PowerShell installer again to update. Windows locks the running
application’s files, so this version gives manual update instructions instead of replacing itself in place.
Git checkouts follow their own GitHub origin and branch. A downloaded source ZIP installs that local source.
The remote installer follows this fork’s `main` branch by default.

Remove the native app with `uv tool uninstall decompnet`. Your projects remain in `%USERPROFILE%\Decomp`.

## Existing WSL installations

The native installer leaves any previous `decomp-wtf` WSL distribution alone. If you have projects in it, copy
those folders from `\\wsl.localhost\decomp-wtf\home\decomp\Decomp` into your Windows projects folder while
WSL is running. Existing projects can refer to Linux tool paths; reselect the matching native compiler in the
app after copying them.

The former WSL installer remains available as `site/public/install-wsl.ps1` for existing installations. It is
separate from `windows.cmd` and is not part of native setup.

## Troubleshooting

If `decomp` is not recognized, open a new terminal or use the Start menu shortcut. If setup fails, its terminal
stays open; include the first error and the command that failed when reporting it. Setup reports unavailable
compilers and failed downloads separately.

If you previously used the WSL launcher and Windows still opens it, rerun native setup to put the new executable
first on your user PATH. `Get-Command decomp -All` in a new PowerShell window shows which commands Windows finds.

A failed import keeps its error and log in the app. The full application log is under
`%USERPROFILE%\Decomp\.decomp\logs`. A compiler failure in one platform does not require reinstalling Windows
features; include the game platform, selected compiler and compile log in the report.

## N64 C++ game output

N64 ROM projects using KMC or IDO 5.3/7.1 default to C++ for drafts, matching and exported builds.
The KMC Windows package includes `cc1plus.exe`; rerun setup to replace the older compiler package.
The IDO packages include each version's original `NCC.exe` and SGI/EDG C++ frontend, `edgcpfe.exe`.
IDO 5.3 uses its own frontend and unchanged 5.3 backend. Both run directly on Windows without WSL. IDO remains an optional proprietary toolchain.
Exports contain `.cpp` files and retain C linkage for the original game's functions and external
symbols. Templates, classes and references are available in each compiler's period dialect:
GCC 2.7.2 for KMC and SGI/EDG 2.19 for IDO 5.3/7.1. KMC's exceptions and RTTI are disabled.
Neither provides a modern C++17/20 compiler or the host computer's standard library.

C++ syntax can produce different bytes from the same C expression. Matching still requires exact
bytes; for example, an absolute-value function may need an explicit conditional assignment in C++.
Existing matched sources are checked again during export, with reported assembly fallbacks if
compilation or matching fails. Explicit `compiler.language = "c"` keeps a project's C compilation.
The classic 5.3 `cfront` driver remains unsupported;
a project explicitly requesting it is never changed automatically to EDG or IDO 7.1. Reinstall
`ido-5.3 --force --accept-license` to add the new native C++ overlay to an older installation.
See [IDO C++ support](ido-cpp.md) for original-IRIX parity checks, rebuild validation and the
remaining classic cfront driver work.

## GBA C++ game output

GBA ROM projects now use a separate native `agbcc-cpp.exe`, restoring the GCC
2.95.3 C++ frontend against the existing agbcc Thumb backend. The pinned Arm GNU
tools preprocess and assemble; their modern GCC compiler does not replace agbcc.
Drafts and exported sources use `.cpp`, with original game C linkage preserved.
Native Windows/Linux tests require real C++ compilation, strict relocation/data
matching and clean byte-identical exported ROM rebuilds. Reinstall an older
package with `decompnet toolchain install agbcc --force`.
See [GBA C++ support](gba-cpp.md) for compiler identity, validation and runtime limits.

## PS1 C++ game output

PS1 GCC 2.7.2 and 2.8.1 projects default to C++ drafts, matching and `.cpp`
exports using the original version-specific GNU C++ frontends. Windows packages
contain standalone native executables and complete corresponding source; WSL is
not required. GCC 2.8.1 uses pinned compatible MIPS binutils for literal labels
that binutils 2.6 cannot parse. Compiler versions and strict relocation/data
matching are preserved. Reinstall an older PS1 toolchain with `--force`.
See [PS1 C++ support](psx-cpp.md) for runtime limits and the required native
Windows/Linux verification gate before publication.
