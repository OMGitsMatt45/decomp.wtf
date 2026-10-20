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

## Classic IDO 5.3 cfront: optional native object compilation

Classic cfront is a distinct pipeline. The optional overlay recompiles the original
`usr/lib/CC`, `usr/lib/c++/cfront`, `ptcomp` and `markc++` for the host. It uses the
already installed, unchanged 5.3 `acpp`, `cc`, `cfe`, `uopt`, `ugen` and `as1`.
The normal installer continues to supply the EDG overlay; classic cfront currently
requires a local build. EDG remains the default.

Build on Linux, or in an MSYS2 build shell on Windows with `gcc make git python tar`
installed. MSYS2 is a build dependency; execution uses the runtime DLLs already
bundled with the installed 5.3 C suite. No WSL or QEMU is used by the application.

```console
bash tools/ido53/build-cfront.sh /path/to/fresh-build /path/to/artifacts
decompnet toolchain install ido-5.3 --accept-license
python -m tools.ido53.install_cfront /path/to/fresh-build/package
```

The build emits an overlay archive, its corresponding recompiler/IRIX input source
archive and checksums. Installation validates the original-input manifest and copies
only the four classic programs and their manifest. The original CC driver is installed
as `classic-CC.exe`, keeping it distinct from `cc.exe` on Windows filesystems.
Reinstalling the base suite with
`--force` removes a manually added overlay, so install it again afterwards.

Select it explicitly in the project:

```toml
[compiler]
toolchain = "ido-5.3"
language = "c++"
cpp_frontend = "cfront"
```

The host adapter copies `.cpp` sources to the `.C` suffix recognized by the original
CC driver, within a private working directory. It rebases include paths and isolates
intermediate files and the template repository. The original CC driver still performs
preprocessing, cfront translation, repository processing, C compilation and object
marking. Exports retain `.cpp` files and record `cpp_frontend = "cfront"`.

The port fixes a patched zero-address load, resolves quickstarted external functions
through their actual GOT entries and dispatches indirect signal callbacks. It supplies
the missing IRIX environment, stdio, file-lock and libC vector services. Temporary
names stay short and relative to the private work folder, fitting IRIX buffers
and avoiding a system `/tmp` dependency on Windows. In particular,
cfront defines its own clearing `operator new`; both direct calls and libC vector
allocation must preserve that definition. Replacing it with ordinary allocation
corrupted later declarations even when a single-function smoke test passed.
The driver's observed `grep`, `sort` and `rm` operations run through bounded host
implementations, without external utilities or a shell.

Verification compares 11 functions with the **unmodified original IRIX cfront** under
QEMU, through the same original 5.3 backend. Final instructions and relocation records
agree exactly; the template/class/constructor/reference probe also produces identical
C text byte for byte. The pinned fixtures include multiple declarations and functions
to catch the allocator regression. QEMU is solely the independent frontend reference.

The [native Windows and Linux CI run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39484029636)
passed all six integration tests and four configuration checks on each host. The
[validation record](ido53-cfront-validation.json) pins the tested source commit,
original input identities, checks and scope. Both installers verified that the
existing C backend files retained identical SHA-256 values.

The native integration suite checks those fixtures, compiles an m2c C++ draft, matches
classic C++ against a homemade C-origin ROM, rejects changed instructions and relocation
destinations, and rebuilds exported `.cpp` files into the identical ROM. It repeats the
build after deleting generated files and restoring sources through Git with
`core.autocrlf=true`. Windows checks remove MSYS from PATH and reject WSL calls.

```console
DECOMP_TEST_IDO_CFRONT=1 python -m pytest tests/test_ido_cfront.py
python -m tools.ido53.verify_cfront --irix-root /path/to/ido/5.3 --qemu /path/to/qemu-irix
```

The IRIX reference needs `libC.so`, linked from the supplied original `libC.a` as described
above. Classic support here covers object compilation, local template instantiation,
application matching and ROM exports. The original IRIX executable linker, `ptlink`
and cross-translation-unit template prelinking are outside this port. Runtime-dependent
game features still require their original target libraries; there are no host C++
standard headers or a modern C++ dialect.
