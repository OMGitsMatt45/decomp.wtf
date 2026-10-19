# IDO C++ game output

IDO 7.1 N64 ROM projects now generate, judge and export real C++ using the original SGI C++
compiler pipeline. IDO 5.3 remains C because a working native C++ frontend is not available in
the pinned package. The compiler version is never changed automatically to accept C++ syntax.

## IDO 7.1

The existing `decompals/ido-static-recomp` v1.2 archives contain `NCC` and `edgcpfe` on Linux,
macOS and Windows. `NCC` selects the SGI/EDG 2.19 C++ frontend and feeds its output through IDO's
original `uopt`, `ugen` and `as1`. Windows uses the native `.exe` programs without WSL. No new
compiler archive or different optimizer is substituted.

The normal project default is C++ for drafts, matching and `.cpp` exports. Plain game functions,
prototypes and external declarations retain C linkage. Templates, classes, references and helpers
with explicit C++ linkage remain C++. This is a pre-standard period dialect, without the host
computer's C++ headers or standard library. Runtime-dependent features require their original
target support; the verified examples need no extra runtime functions.

IDO is still an optional proprietary toolchain with the existing explicit installation choice:

```console
decompnet toolchain install ido-7.1 --accept-license
```

Existing installations already contain the frontend. If files are missing, reinstall with
`--force`. An explicit project setting preserves the original C frontend:

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
generated assembly, assets and build output. WSL calls fail these tests. Paths include spaces.

Reference generation (after installing the pinned Linux toolchain):

```console
python tests/fixtures/generate_native_compiler_parity.py --toolchain ido-7.1 --language c++
DECOMP_TEST_IDO_CPP=1 python -m pytest tests/test_ido_cpp.py
```

## Why IDO 5.3 remains C

The v1.2 Linux and Windows 5.3 packages contain the C frontend, `cfe`, but no C++ `cfront` or
compatible C++ driver. Renaming `cc` to `CC` and passing a `.cpp` source still invokes `cfe`:
`__cplusplus` is absent and templates and `extern "C"` produce syntax errors. `-Xcpluscomm` only
allows C++-style comments in C; it does not select a C++ frontend.

The upstream repository does include the original IRIX MIPS binary at
`ido/5.3/usr/lib/c++/cfront`. That binary is not a native Windows or Linux program. An attempt to
statically recompile it with upstream revision `d5aec59` failed:

```console
make -j4 RELEASE=1 setup
make -j4 RELEASE=1 VERSION=5.3 IDO_TC=cfront
```

The first failure is `Insn::getAddress()` on a patched load-address instruction whose address is
zero (`0x00469658`, original instruction `0x8f9080b4`). An experimental fix for that case gets
farther but then fails on `missing extern function: __vec_dt`. The frontend also imports vector
construction/allocation routines (`__vec_ct`, `__vec_new`), `__pure_virtual_called` and other
functions not covered by the recompiler's host runtime bridge. Those bridges, guest callbacks,
driver/preprocessor integration and output parity need implementation and validation. The
experimental recompiler edits and an unverified compiler are not shipped.

Concrete paths forward:

- Complete a native static recompilation of the **5.3** frontend and its runtime bridge, then
  validate it against the original IRIX frontend and the original 5.3 backend. The IRIX environment
  can provide a reference; it does not satisfy native Windows execution for users.
- Investigate a source-built `cfront` implementation, but prove dialect, ABI and generated output
  compatibility first. A different `cfront` release is not automatically the SGI 5.3 frontend.
- Select IDO 7.1 or KMC explicitly for a project that targets that compiler. This changes the
  compiler and does not establish a matching decompilation of an IDO 5.3 game.

IDO 5.3 therefore keeps its working native C pipeline and reports the missing `cfront` explicitly
if C++ is requested. Its C compiler is exercised by the integration checks on both operating systems.
