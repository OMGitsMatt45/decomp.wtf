# IDO C++ game output

IDO 5.3 and 7.1 N64 ROM projects generate, judge and export real C++ using each version's
original SGI/EDG frontend and original IDO backend. Both run natively on Windows and Linux
without WSL. The app identifies the frontend as **SGI/EDG 2.19**, and exported `build.json`
records `cpp_frontend = "edg"` by default. A separate optional classic AT&T-derived
`cfront` overlay can be built for IDO 5.3. Missing classic components fail explicitly;
the application never substitutes EDG or another compiler.

## IDO 7.1

The existing `decompals/ido-static-recomp` v1.2 archives contain `NCC` and `edgcpfe` on Linux,
macOS and Windows. `NCC` selects the SGI/EDG 2.19 C++ frontend and feeds its output through IDO's
original `uopt`, `ugen` and `as1`. Windows uses the native `.exe` programs without WSL. The SGI
compiler programs and target algorithms are unchanged.

The original Windows 7.1 package failed before compilation because its guest libc address,
`0x0fb4c000`, is not aligned to MSYS's 64 KiB pages. The Windows package is rebuilt from v1.2
with the containing libc page mapped. Its assertion reporter also uses a portable diagnostic
and abort, avoiding an obsolete host `__assert` calling signature. Runtime DLLs are bundled
beside the executables, including with the existing 5.3 C package, so a separate MSYS installation
is not required. Linux keeps its original pinned package. The build recipe, recompiler source
archive with its original IRIX inputs, and corresponding MSYS runtime source accompany the Windows assets.
The [pinned asset commit](https://github.com/OMGitsMatt45/decomp.wtf/tree/1d7f59df57cd61805ae9f18cad33ae8d65845623/toolchains/windows/ido)
contains their checksums and instructions for joining the complete runtime source archive.
The application also supplies a writable Windows temporary directory for every compile, rather
than relying on an MSYS `/tmp` directory. IDO uses relative source/object names inside the work
folder because its legacy tools truncate absolute output paths containing spaces. The Windows
temporary folder uses its short path when needed. If the filesystem provides no short alias,
the error explains how to select a writable temporary directory without spaces using TMP/TEMP.

The normal project default is C++ for drafts, matching and `.cpp` exports. Plain game functions,
prototypes and external declarations retain C linkage. Templates, classes, references and helpers
with explicit C++ linkage remain C++. This is a pre-standard period dialect, without the host
computer's C++ headers or standard library. Runtime-dependent features require their original
target support; the verified examples need no extra runtime functions.

IDO is still an optional proprietary toolchain with the existing explicit installation choice:

```console
decompnet toolchain install ido-7.1 --force --accept-license
```

Reinstall older Windows packages to get the host fix and bundled runtime. An explicit project
setting preserves the original C frontend:

```toml
[compiler]
toolchain = "ido-7.1"
language = "c"
```

Changing the source language can change instruction selection and register allocation. C++ does
not make every existing C source match automatically. Existing matches are checked again during
export and fall back to assembly with an explanation if they differ. Exact code, relocation and
referenced-data checks remain required.

The required Windows and Linux integration checks compile actual templates, classes and references
with a `__cplusplus` guard; compare eight functions against a pinned Linux C++ code-and-relocation
reference; and build a homemade ROM using the IDO **C** compiler. Four functions of that C target
are then matched as C++, including a template/class/reference example, a call and a global data
reference. The `.cpp` export must rebuild that ROM byte for byte, then rebuild again after removing
generated assembly, assets and build output. Changed instructions and relocation destinations
must fail matching. WSL calls fail these tests. Paths include spaces, and Windows tests remove
MSYS from PATH. Exported code and headers use LF line endings, with `.gitattributes` preserving
them when Git for Windows restores a clone with `core.autocrlf=true`.

Reference generation (after installing the pinned Linux toolchain):

```console
python tests/fixtures/generate_native_compiler_parity.py --toolchain ido-7.1 --language c++
DECOMP_TEST_IDO_CPP=1 python -m pytest tests/test_ido_cpp.py
```

## IDO 5.3: authentic SGI/EDG C++

The original 5.3 distribution contains **two** C++ frontends: the classic
`usr/lib/c++/cfront` and SGI/EDG 2.19 at `usr/lib/DCC/edgcpfe`. The earlier native package
included neither. IDO 5.3's own `cc` driver selects its EDG frontend when named `NCC`.
The new native overlay supplies that driver and **the 5.3 EDG binary**, not the 7.1 binary.
Their original IRIX SHA-256 values are different:

| Original frontend | SHA-256 |
| --- | --- |
| IDO 5.3 `edgcpfe` | `c7d5bdd0c730d2dbb9e5004ba69fcac48e08c9767af10b71ab2234beb73de3cc` |
| IDO 7.1 `edgcpfe` | `18b70b1f90cab9197868e6a1bd0a0d13c1ee4a1eb423e43d6fc24cf964278715` |

The overlay leaves the pinned 5.3 `cc`, `cfe`, `uopt`, `ugen` and `as1` files unchanged.
Its static recompiler is pinned to `decompals/ido-static-recomp`
`d5aec59932034b8a20f23f471297a55c45dcbc45`. The patch recognizes two bounded jump tables
in `make_variable` and `matches_template_type`; both bounds are checked against the actual
MIPS instructions. The Windows host memory/assertion fixes also apply. The compiler's target
algorithms are not rewritten. The build recipe, patch, original-input checksums and corresponding
recompiler/IRIX input archive accompany the packages. Windows uses the already pinned bundled
MSYS runtime and its published complete corresponding source; no system MSYS installation is needed.
The [immutable overlay assets](https://github.com/OMGitsMatt45/decomp.wtf/tree/c69498c622bfa77fe36fe2a0bb2ce258c7263608/toolchains/ido53-cpp)
include SHA-256 checksums for both native packages and their corresponding source archives.

Install or update the optional proprietary suite:

```console
decompnet toolchain install ido-5.3 --force --accept-license
```

C++ projects select the original 5.3 SGI/EDG pipeline:

```toml
[compiler]
toolchain = "ido-5.3"
language = "c++"
cpp_frontend = "edg"
```

These are also the N64 ROM defaults for this toolchain. An explicit `language = "c"` retains
the original 5.3 C pipeline. The new C++ overlay is packaged for Windows/Linux x86-64; macOS
keeps the existing C package and reports an explicit error if 5.3 C++ is requested.

Verification compares the native frontend with the **unmodified original IRIX 5.3 `edgcpfe`**
running under QEMU, through the same pinned 5.3 backend. Eleven functions cover calls, external
data relocations, branches, floating point, templates, class constructors and references.
Final machine code and relocations must agree exactly. Raw Ucode records contain unused
uninitialized padding, so raw intermediate files may differ; no final instruction/relocation
bits are masked. Pinned reference fixtures are checked on both Windows and Linux. QEMU is
only the reference harness, never an application dependency.

Both suites also build a C-origin homemade ROM, match four functions as C++, reject changed
instructions and changed relocation destinations, and export `.cpp` files that rebuild the
entire ROM byte for byte. A second rebuild starts without generated assembly, assets or build
output, after a Git checkout with `core.autocrlf=true`. Windows tests exclude MSYS from PATH
and reject WSL invocations. m2c drafts request the `mips-ido-c++` target.

To reproduce the IRIX reference comparison, build `libC.so` from the supplied original `libC.a`
using the original IRIX `ld` under QEMU (the upstream tree omits the shared library):

```console
chmod +x "$IRIX_ROOT/usr/lib/ld" "$IRIX_ROOT/usr/lib/DCC/edgcpfe" "$IRIX_ROOT/lib/rld"
"$QEMU_IRIX" -L "$IRIX_ROOT" "$IRIX_ROOT/usr/lib/ld" -shared -all \
  "$IRIX_ROOT/usr/lib/libC.a" -o "$IRIX_ROOT/usr/lib/libC.so" -L"$IRIX_ROOT/usr/lib" -lc
python -m tools.ido53.verify_irix --irix-root "$IRIX_ROOT" --qemu "$QEMU_IRIX"
DECOMP_TEST_IDO_CPP=1 python -m pytest tests/test_ido_cpp.py
```

The verified reference harness is `n64decomp/qemu-irix` release `v2.11-deb`. It reports an
unsupported `sgisysinfo(106)` query when the frontend's verbose banner is enabled; compilation
completes, and the final code and relocation comparisons pass. Source-built replacement cfront
or a switch to 7.1/KMC is unnecessary for this supported 5.3 EDG path.

## Classic IDO 5.3 cfront and template prelinking

The normal `ido-5.3` installation now includes both original frontend choices on
Windows and Linux x86-64. EDG remains the default. Refresh an older installation:

```console
decompnet toolchain install ido-5.3 --force --accept-license
```

Select classic cfront explicitly:

```toml
[compiler]
toolchain = "ido-5.3"
language = "c++"
cpp_frontend = "cfront"
```

Classic support recompiles the original `usr/lib/CC`, `cfront`, `ptcomp`,
`markc++` and `ptlink`. It retains the installed, unchanged 5.3 `acpp`, `cc`,
`cfe`, `uopt`, `ugen` and `as1`. The classic driver is named `classic-CC.exe`,
keeping it distinct from `cc.exe` on case-insensitive Windows filesystems.
Missing classic components fail explicitly; EDG is never substituted.

The application adapter copies `.cpp` sources to the `.C` suffix accepted by the
original driver, isolates intermediate files and rebases include paths. Exports
retain `.cpp` files and `cpp_frontend = "cfront"`. Original compiler algorithms
perform preprocessing, C++ translation, repository processing, C compilation
and object marking. Host fixes cover quickstarted GOT imports, a legitimate
zero-address load, callback dispatch, IRIX environment and stdio, file locking,
short relative temporary names and libC vector services. In particular, cfront's
own clearing `operator new` must remain active for direct and vector allocation;
ordinary allocation corrupted later declarations in multi-function inputs.

The original `ptlink` now supports separate template declarations, definitions
and callers. For a project compiled with `classic-CC -c` into a shared
`ptrepository`, prelink and combine its objects with:

```console
python -m decompnet.ido_prelink --work /path/to/project --output combined.o left.o right.o
```

Add `--include include` for additional include directories. Flags after `--`
replace the default IDO flags. The working directory may contain spaces; relative
object, repository and include arguments must fit the original driver's grammar
and contain no whitespace. The command supplies the original prelinker's control
files, then invokes the pinned N64 GNU linker with `-r`. It replaces the requested
output only after successful instantiation and linking. The previous output
survives invalid template definitions or other prelink failures.

The adapter fingerprints project and include-file contents, compiler flags and
installed manifests before reusing template objects. Transitive header edits
invalidate them even with unchanged or older timestamps. The repository must
be a subdirectory of the working directory. Recompile caller objects separately
when a dependency changes their own class layout or inline code.

Direct `classic-CC` invocations need LF source/header files, as the original
IRIX tools expect. The matcher and standalone exports accept CRLF edits and
normalize staged sources and nested includes without changing the user's files.

Cross-unit prelinking is a shared-project operation. The application's independent
function compilations continue to isolate their repositories. This does not add
a full IRIX executable environment, `c++patch` startup processing, or IRIX shared
library linking. Target runtime references still need the game's compatible
libraries; no modern host C++ standard library or dialect is supplied.

The [native Windows/Linux compiler and prelink verification](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39491288285)
passes seven integration tests and four configuration checks per host, with zero
required skips. Coverage includes original-IRIX code/relocation fixtures, C++ m2c
drafts, C-origin ROM matching, wrong-code/relocation rejection, clean exported
rebuilds after deleting generated files and Git autocrlf checkout, and cross-unit
template dependency invalidation. Windows removes MSYS from PATH and rejects WSL.
The original C backend hashes remain identical after overlay installation.

Independent reference checks compare 11 functions and the generated C text with
unmodified IRIX cfront under QEMU. The cross-unit instantiation C text also matches
byte for byte. QEMU is only the reference harness, never an application dependency.
See the [validation record](ido53-cfront-validation.json) and
[compiler completion record](compiler-completion.md).

The [immutable classic binary/source packages](https://github.com/OMGitsMatt45/decomp.wtf/tree/5e4d52c7a28e3f25ce62c6ae5065839f0c3b96e7/toolchains/ido53-cfront)
include corresponding recompiler sources and original IRIX inputs. For a local
rebuild, use `tools/ido53/build-cfront.sh` in a fresh directory; MSYS2 is a Windows
build dependency, while normal installation only needs the bundled runtime DLLs.
The [build guide](../tools/ido53/README-cfront.md) documents that optional workflow.
