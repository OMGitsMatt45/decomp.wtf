# EE-GCC 2.96 source reconstruction: built, compatibility failed

The source-build experiment produced Linux i386 ELF and Windows i386 PE versions
of `cc1`, `cc1plus`, `xgcc` and `cpp0`. **It did not reconstruct a compatible
`2.96-ee-001003-1` compiler.** Neither candidate passed the C++ compilation corpus;
no matching or clean exported-project rebuild is established with either one.
They are not registered, installed or selected by decomp.wtf.

The reconstructed source remains incompatible. A separate
[original-binary Windows host](../tools/ps2_cpp/elf_host/README.md) now provides
native Windows support without reconstructing the missing source. The source-build experiment below is separate
from the functioning [original-compiler implementation](ps2-cpp.md).

## Source inputs and work completed

The [input manifest](../tools/ps2_cpp/reconstruction/inputs.json) pins:

- GNU GCC **2.96 20000914 (experimental)**, commit
  [`597c1b34`](https://github.com/gcc-mirror/gcc/tree/597c1b349fcbda26ba75a4e3a4fb136c26887d7a).
  The inspected October 3 GNU snapshot is already **2.97**, so its date alone
  does not identify the requested vendor compiler.
- The available EE backend from
  [`SSXModding/ps2-ee-toolchain@b595ded6`](https://github.com/SSXModding/ps2-ee-toolchain/tree/b595ded606227e93b8c4a447446c1d2ac093827d/ee/gcc),
  whose version is **2.9-ee-991111**. This is an older backend, not recovered
  2.96 EE source.
- The user's recovered `sce-patch` and two installed intrinsic headers from
  `ee001003_1.7z`, all checked by SHA-256. The full patch hash is
  `1fba1eae60d1625d9cab841267766bccea54ee0080f6257294798e51a85b4735`.
  Its GCC sections are selected separately and hashed. SDK programs are not
  executed by the preparation recipe; SDK payloads are not committed here.

The [preparation script](../tools/ps2_cpp/reconstruction/prepare.py) overlays
the older EE target, applies the recovered GCC patch with zero fuzz, retains
its rejects, and applies the experimental
[compatibility patch](../tools/ps2_cpp/reconstruction/compat.patch). The latter
adapts old GCC APIs and machine-description constraints, modern host C syntax,
MinGW configure/process declarations and mmap guards, target address defaults,
and GNUPro's 64-bit `HOST_WIDE_INT` requirement on 32-bit hosts. It does not
disable machine-description validation or manufacture the missing optimizer.

The candidate identifies itself as:

```text
2.96 20000914 (EE reconstruction experiment; NOT Sony 2.96-ee-001003-1)
```

Fresh preparation reproduced **118 recorded source-file hashes**. Both host
builds then completed from fresh source/build directories using the checked-in
recipe and native Bison 1.25. Build-host GCC was Debian 14.2.0; Windows output
used i686 MinGW GCC 14-posix. Compiler host code used
`-O0 -fno-strict-aliasing -fwrapv`; this does not change the game optimization
flags being compared. The Windows C++ frontend imports only `ADVAPI32.dll`,
`KERNEL32.dll` and `msvcrt.dll`.

Only compiler programs were built. There is no completed target libgcc,
libstdc++, SDK installation or packaged Windows assembler/linker in this
experiment. Building PE files does not establish a usable native Windows
toolchain.

## Measured results and limits

The [probe](../tools/ps2_cpp/reconstruction/probe.py) retains the original
2.96 driver and EE assembler. A counted `-B` wrapper selects the candidate
`cc1plus` explicitly, preventing accidental fallback to the original frontend.
Both sides use the same game symbol linkage handling and real C++ language
selection. Sources contain `__cplusplus` guards, templates, classes, references
and explicit C++ overloads.

The corpus combines the existing seven-function PS2 fixture and an
[extended fixture](../tools/ps2_cpp/reconstruction/extended.cpp) with integer,
64-bit, floating-point, call, loop, switch, structure, string, table and small
global probes. Each runs at `-O2 -G8`, `-O2 -G0`, `-O0 -G8`, `-O1 -G8`, and
`-Os -G8`. When compilation succeeds, the harness compares function bytes and
relocations, extra/missing functions, allocated data bytes, BSS size/alignment
and data relocations. Any compilation or comparison failure returns exit 1.

| Clean candidate build | Execution actually checked | Compilation results |
| :-- | :-- | :-- |
| Linux ELF32 | QEMU i386 on Linux | 0/10 successful; original driver reports frontend floating-point exceptions |
| Windows PE32 | wibo on Linux | 0/10 successful; original driver reports frontend segmentation faults |
| Original pinned Linux compiler | QEMU i386 on Linux | All 20 reference compilations succeeded |

The full records include frontend hashes, source hashes, reference-description
hashes, invocation counts and diagnostics:
[Linux](../tools/ps2_cpp/reconstruction/results/linux32.json),
[Windows PE under wibo](../tools/ps2_cpp/reconstruction/results/windows.json),
and [build/provenance record](../tools/ps2_cpp/reconstruction/results/build.json).
Earlier partially matching LP64 experiments had incorrect host-width handling
and floating constants; they are not compatibility evidence.

These are local emulation results. **The reconstructed compiler was not verified
on native Windows or native Linux, and no reconstructed-compiler export rebuild
passed.** The crash sites have not been traced to a particular source line;
loader/emulator effects are not ruled out. A passing native run would still
need byte, relocation, data and export validation before enabling this backend.

The existing original-compiler PS2 regression suite also passed locally:
**16 passed, zero skips**, including matching, C++ drafts and clean export checks.
Those compiler executions used QEMU; prior native Linux CI evidence remains in
[the support document](ps2-cpp.md#verification).

## Precise remaining source and compatibility gaps

The uploaded `sce/ee/gcc/src/` is empty. Its incremental patch starts from
**already EE-patched GNUPro 2.96**, not stock GNU GCC. Replacing that missing
base with the older EE backend leaves unresolved changes in `mips.c`,
`mips.md`, `t-r5900` and the R5900 floating-point configuration. The preparation
record preserves the original partial-application failures, including the
missing `config/float-r5900.h`; its intentionally retained experimental version
also rejects Sony's version-relabeling hunk.

The original frontend's ELF STABS records also identify GNUPro source files
absent from the chosen GNU tree:

- `range.c`: 14 recorded functions, including `live_range`, `range_inner` and
  `range_scan_blocks`. Original verbose compiler output enables `-flive-range`
  and `-fdelay-postincrement`. These optimizer differences matter to exact code
  generation.
- `cppobscure.c`: 17 recorded functions implementing obscured-header support.
  This is a further source gap; it has not been identified as the crash cause
  or a prerequisite for ordinary game source.

The [recorded function names](../tools/ps2_cpp/reconstruction/results/vendor-source-gaps.json)
come from the pinned original `cc1plus`, SHA-256
`560e6f276134d109e2b4c05ee9c72d4f9215ffc86d784eb4491a3dadf316bf9a`.
Thus a successful build of the mixed tree would still require substantial
vendor-core/backend reconstruction and parity work. It cannot be certified
as the original EE compiler by editing a version string or matching a few
small functions.

The direct path remains obtaining the corresponding GNUPro EE base
`sce/ee/gcc/src/src.tar.gz`, or an authentic Windows build. Reconstructing the
remaining vendor code is an open compiler-development project. PS2DEV's modern
compiler, older 2.9 EE and SN 2.95 can only be separate explicitly named
backends; none establishes 2.96 parity. Running the exact original binary via
an explicit emulator is another separate path, with Windows process/filesystem
and full export validation still required. No fallback was added. PlayStation
PR #2 remains unmerged; classic IDO 5.3 remains parked.

## Reproducing the experiment

Use a Linux build host with Python 3.12+, GNU make, patch, GCC, a working 32-bit
C development environment and i686 MinGW GCC. The measured host used a local
32-bit sysroot/compiler wrapper; a configured multilib installation can use
`gcc -m32` instead. The build script records its exact commands in the work
directory and preserves logs. Use separate prepared trees for concurrent host
builds because Bison generates parser files in the source tree.

Fetch the pinned GNU archive and EE checkout from the manifest. Extract the
user-supplied SDK separately, then set `EE_SOURCE` to the checkout's `ee/gcc`
directory and `EE_SDK` to the recovered `sce/ee/gcc` directory. From this repo:

```sh
python tools/ps2_cpp/reconstruction/prepare.py \
  --gnu-archive work/gcc-20000914.tar.gz --ee-source "$EE_SOURCE" \
  --sdk "$EE_SDK" --output work/ee296-linux-source
```

Preparation prints the resulting source path. It checks all pinned inputs,
Sony reject hashes and the final source hashes, and requires a fresh output
directory. It intentionally does not claim that the recovered patch applies
cleanly to these different sources.

Build native Bison 1.25 from the same pinned EE checkout's `ee/bison` directory
in a separate directory with its `configure` and `make`. Let `BISON_EXE` point
to that built `bison`, `BISON_DATA` to its source directory containing
`bison.simple`/`bison.hairy`, and `CANDIDATE_SOURCE` to the prepared source path.

```sh
python tools/ps2_cpp/reconstruction/build.py \
  --source "$CANDIDATE_SOURCE" --work work/ee296-linux-build \
  --host linux32 --cc 'gcc -m32' \
  --bison "$BISON_EXE" --bison-data "$BISON_DATA"

# Prepare a second source tree first and set CANDIDATE_SOURCE to it.
python tools/ps2_cpp/reconstruction/build.py \
  --source "$CANDIDATE_SOURCE" --work work/ee296-windows-build \
  --host windows --cc i686-w64-mingw32-gcc \
  --ar i686-w64-mingw32-ar --ranlib i686-w64-mingw32-ranlib \
  --bison "$BISON_EXE" --bison-data "$BISON_DATA"
```

To measure parity, install the existing pinned `ee-gcc-2.96` toolchain and the
project's Python dependencies. On Linux, run the explicit candidate through
the harness. For the Windows binary, the measured invocation is:

```sh
python tools/ps2_cpp/reconstruction/probe.py \
  --frontend work/ee296-windows-build/gcc/cc1plus.exe \
  --runner /path/to/wibo --execution 'wibo on Linux; not native Windows' \
  --work work/ee296-windows-probe
```

For the Linux candidate use `--frontend .../gcc/cc1plus` with a configured
QEMU runner such as `--runner 'qemu-i386 -R 1G -L /path/to/i386-sysroot'` and
an accurate `--execution` label. The original Linux driver/assembler also need
a runnable environment. Set `DECOMPNET_TOOLCHAINS` if using a nondefault install
directory. The current expected probe result is failure, recorded in
`report.json`; it is not a successful compiler smoke test.
