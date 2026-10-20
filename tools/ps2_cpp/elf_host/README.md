# Original EE 2.96 on Windows: experimental native x86 host

This is a new approach to the missing Windows compiler, separate from the failed
source reconstruction. It builds **Win32 PE executables containing the original
Linux i386 compiler programs**. Their original x86 instructions run on the CPU;
there is no MIPS translation, CPU interpreter, WSL, Linux VM, or replacement GCC
backend in this host. The app can select a locally built host explicitly through
`DECOMP_EE_NATIVE_ROOT`; an automatic Windows download bundle is not published.

## What changed at the host boundary

The loader maps the original ELF load segments at their original addresses,
binds dynamic imports to Win32/MinGW adapters, and calls the original `main`.
The original compiler payload is embedded read-only in each host executable;
external ELF files cannot be substituted after the build. The original archive
and GNU helper sources are checksum-verified before building.

Adapters implement the old glibc stdio layout, character tables, stat layout,
memory mapping, nonlocal jumps, process timing and related C-library services.
The original assembler uses GNU getopt and obstack through the same boundary.
Host x87 initialization preserves Linux i386's extended precision.

The **driver only** also receives two explicit five-byte host detours:
`pexecute` and `pwait`, libiberty's process-launch/wait functions. These use
Windows spawning and argument quoting instead of Unix fork/exec. Driver option
specs, frontend, optimizer, target backend and assembler algorithms remain the
original binary instructions. Detour addresses and every original payload hash
are recorded in `host-build.json`.

Unimplemented imports fail with exit 126 **if called**, naming the operation;
they never return manufactured success. `-pipe` is explicitly unsupported.

## Why the supplied projects did not directly solve the compiler problem

Inspected commits:

| Project | Commit | Relevant finding |
| --- | --- | --- |
| [PS2Recomp](https://github.com/ran-j/PS2Recomp) | `eb8688b2fd191129f103a39543002c005b33409c` | Translates PS2 R5900 instructions to C++ and supplies a PS2 runtime. It does not translate the Linux/i386 EE compiler. |
| [psretrox](https://github.com/cualquiercosa327/psretrox) | `a7bd9384cf528bd2ee7da6f854e4f59f8829f086` | Game extraction/disassembly and incomplete recompilation tooling; no runnable EE compiler or Linux libc host. Its inspected Capstone wrapper is configured for x86, despite the PS2-facing UI. |
| [ico-pc](https://github.com/nathanialf/ico-pc) | `90673d2077f336f6f7ecb9836f4c6c1d34f99a57` | A game-specific PC port. Its fetched compiler is a modern PC host compiler, not the original EE-GCC 2.96 backend. |

None supplies the missing corresponding GNUPro EE source. The host approach
avoids reconstructing that source by preserving the existing compiler binary.
No source from these three projects is incorporated.

## Build

Use this repository's Python environment and an i686 MinGW C compiler/binutils.
Build dependencies are separate from the resulting programs' runtime needs.

```sh
python tools/ps2_cpp/elf_host/build.py \
  --archive /path/to/ee-gcc2.96.tar.xz \
  --output '/path/to/fresh Windows toolchain' \
  --cc /path/to/i686-w64-mingw32-gcc \
  --objcopy /path/to/i686-w64-mingw32-objcopy
```

The archive is the existing decomp.me `compilers/ee-gcc2.96.tar.xz`, SHA-256
`0590d2ca9da8f5903889d66761220d14b47a8d14ba987ca53db84a1650a1fd0a`.
The script builds the original driver, C frontend, C++ frontend, preprocessor
and assembler, plus their driver aliases. Nothing is installed into the app.
GNU obstack/getopt source, checksums and generated metadata accompany the local
research build. No compiler binary package is published by this workflow.

## Validation and limits

`probe.py` runs the **full original driver/frontend/assembler pipeline**. Its
corpus covers both feature fixtures at five optimization/GP settings, the
13-function C game at those settings, additional floating-point constants,
quoted macro arguments, headers in a directory with spaces, invalid C++, a
missing header and rejection of C++ by the C frontend. Successful cases compare
**complete object-file SHA-256**, including code, relocations and data. Negative
cases require the reference exit status and no object. Source/header hashes and
flags are pinned in `reference.json`; empty or stale runs cannot pass.

The final **22/22** local run passed under **wibo on Linux**, with the unchanged
Linux reference executed through **QEMU i386**: 18 compilations with identical
complete object files, one identical standalone-preprocessor output, and three
matching failure/no-output checks. This includes floating constants after
explicit x87 initialization. See [the measured report](results/wibo-linux.json)
for binary hashes, metadata and actual execution labels. These are compatibility
runner results. The subsequent
[native Windows validation](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39446829628)
passed **all 22 parity checks and all 16 matching/export tests with zero skips**
on Windows Server 2022 x64. The compiler runs with System32-only PATH. No WSL,
wibo, QEMU or system MSYS runtime is involved in that native execution.

```sh
python tools/ps2_cpp/elf_host/probe.py \
  --candidate-command 'wibo "/path/to/Windows toolchain/bin/ee-gcc.exe"' \
  --reference-command /path/to/explicit-linux-reference-wrapper \
  --execution 'Windows PE under wibo on Linux; reference under QEMU i386' \
  --work '/path/to/fresh parity directory with spaces'
```

On Windows, omit wibo and use `--golden tools/ps2_cpp/elf_host/reference.json`
instead of `--reference-command`. The GitHub workflow gives the exact invocation.

The existing PS2 integration suite also passed **16 tests, zero skips**, using
the Windows hosts under wibo: C/C++ matching of all 13 game functions, strict
instruction/call/GP/table/data negatives, C/C++ exports, byte-identical flat
payload and reconstructed ELF, and clean rebuilds after deleting generated
files and restoring sources with Git autocrlf. See the
[integration summary](results/integration-wibo-linux.json) and
[current-run JUnit results](results/integration-wibo-linux.xml).

`integration.py` uses the application's real local-build configuration on Windows.
Linux measurements use a temporary research provider and shell launch shim for
wibo. It does not edit the registry file, disable matching assertions or change
the tests. Its test bodies already select the native/no-sandbox
compiler mode. Install `binutils-mips`, `m2c` and prepare the zlib demo sources
before running it, as the dedicated workflow does. Example on Windows:

```powershell
python tools/ps2_cpp/elf_host/integration.py `
  --toolchain 'C:/path/to/Windows toolchain' `
  --work 'C:/path/to/fresh integration results'
```

## Use the local build in the app

On Windows x64, select the **absolute** output directory from the verified build:

```powershell
$env:DECOMP_EE_NATIVE_ROOT = 'C:/DecompTools/EE host'
uv run --no-sync decomp --no-browser
```

The app checks the build metadata's original archive identity and all five
Windows executables. It uses the original EE compiler's C/C++ settings and
Windows driver directly, without the Linux runtime dependency. A configured
local host takes priority over the optional legacy WSL bridge for this compiler.
An incomplete build reports an explicit error. `toolchain install --force`
refuses to delete a user-managed local host; rebuild into a fresh directory.
Other platforms and the default toolchain location are unaffected.

The compiler driver imports only KERNEL32 and MSVCRT. Unsupported ABI
paths, locale/Unicode edge cases, process pipelines and address-space conflicts
are not established by this finite corpus. Without the explicit local-build
setting, Windows still reports the missing downloadable EE compiler package.
