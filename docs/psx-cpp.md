# PS1 C++ game output

PS1 ROM projects using `gcc-2.7.2-psx` or `gcc-2.8.1-psx` default to C++
drafts, compilation, matching and `.cpp` exports. Explicit
`compiler.language = "c"` retains C. Older exported projects without a language
field continue to compile as C.

Eligible disc imports also [reconstruct the complete original image](psx-disc.md)
from the independently rebuilt boot program and discovered overlays. Supported
CHDs retain their original container after matching and support lossless mod
recompression. Unsupported filesystem layouts retain program-only exports.

For sequential recovery without an AI agent, use the console:

```sh
decompnet --db "work/app.db" psx recover PROJECT --workspace "work/projects" --limit 200 --max-insns 24
```

It tries integer/memory-leaf candidates and m2c drafts, saving only exact compiler and
full-link matches. `--search-profiles` also probes installed original GCC
versions at O0/O1/O2, G0/G8 and installed assembler profiles, retaining improved
saved source candidates. It persists a profile only after a match. Reruns skip
matched functions; unresolved functions remain assembly. See the
[console recovery guide](psx-resources.md#recover-cc-without-an-ai-agent).

## Compiler identity

These are the **original GNU C++ frontends for each PS1-patched GCC version**,
from decompals/old-gcc release 0.17, not renamed C files or a modern replacement
compiler. The Linux release already contains `cc1plus`. Windows packages add
standalone MinGW PE32 builds of that same frontend; GCC 2.8.1 also gains its
native C driver, preprocessor and C frontend. Windows execution needs no WSL,
MSYS or Cygwin runtime.

| Version | Compiler source | Assembler |
| :-- | :-- | :-- |
| GCC 2.7.2 PS1 | Original AzureFlute import `2d758772bde54b0161ad380d11da13efdebfd261` plus old-gcc 0.17 PSX patches | Existing pinned binutils 2.6 |
| GCC 2.8.1 PS1 | Original GNU 2.8.1 tarball, SHA-256 `3b30fbfdf93e628373d90d174243f3267b0eec9ebe792bb64fd15b8828c2ea4c`, plus old-gcc 0.17 PSX patches | Pinned binutils-mips v0.10 on Windows and Linux |

Both use target patches from old-gcc commit
`cf70ec58bce58128732062bc9930045c82904cbb`. Host changes cover Windows process
quoting, child exit status, temporary files, modern varargs headers and build
compatibility. Target instruction selection, optimization and register allocation
are unchanged. Binutils 2.6 misparses GCC 2.8.1's `%hi($LC0)` literal labels;
the compatible assembler is selected explicitly rather than changing compilers.
GNU assembly is not a claim of exact ASPSX/PSY-Q assembler compatibility.
Per-function `--assembler maspsx-2.56` or `maspsx-2.86` selects the pinned maspsx
translator between the original compiler and GNU assembler. Selecting either
profile automatically installs its dependencies and preserves the selection in
standalone builds. These profiles reproduce supported period scheduling and
instruction expansion; they do not establish compatibility with every ASPSX
release or handwritten assembly extension.

Architectural GP save/restore wrappers may use a standalone global declaration
`register unsigned int psx_gp asm("$28");` with either registered PS1 GCC.
Only this explicit register binding is accepted; instruction assembly, other
register bindings, initializers and custom compiler commands remain excluded.
These hardware wrappers are architecture-specific C. Ordinary small globals
continue to use module GP facts and normal C declarations.
The pinned Linux binutils-mips binaries require glibc 2.38 or newer (for example,
Ubuntu 24.04); this also applies to PS1 exported-project linking.

`tools/psx_cpp/build.py` and `tools/windows/build-psx{272,281}.py` build the
Windows packages. The [verified binary/source packages](https://github.com/OMGitsMatt45/decomp.wtf/tree/ca4d1c635680edbfdf40c3028c0d6dcdcb5d42ff/toolchains/ps1-cpp) include licenses, complete corresponding GPL
sources, target patches and the build recipe in `cpp-source/`. Registry URLs
pin immutable asset commits and SHA-256 checksums. Reinstall older installations:

```sh
decompnet toolchain install gcc-2.7.2-psx --force
decompnet toolchain install gcc-2.8.1-psx --force
```

## Language, linkage and strict matching

This is the pre-C++98 GNU dialect supported by each period frontend. Templates,
classes, local constructors, references and explicitly overloaded helpers are
available. Exceptions and RTTI are disabled. No modern standard library, C++
startup code or compatible implementation of `new`/`delete` is supplied. Global
dynamic initialization and code needing a C++ runtime require separate game
support and are not established by this conversion.

Plain game functions, prototypes and external variables retain the game's C
linkage. Templates, classes, static helpers and explicit `extern "C++"` helpers
keep their authored linkage. Judge and exported builds apply the same rules.
`-fconserve-space` preserves C-style common storage for uninitialized small-global
declarations in the context; it prevents duplicate definitions across exported
translation units while retaining `$gp` access. Per-unit headers travel with
their functions.

C++ can emit different instructions for equivalent C expressions. The demo's
absolute-value function uses an explicit conditional assignment, its null macro
is `0`, and two loops declare their entity pointer outside the loop. These are
authored matching candidates, not automatic rewrites of submitted bodies.

Matching requires exact instructions, resolved call and data relocations, and
the owned data referenced by the candidate. Local GP relocations honor the
input object's `.reginfo` GP bias, including binutils 2.6's `0x4000`. Indexed
loads validate the entire constant table rather than just its first element.
Every exported PS1 build runs the same strict checks before linking, then
compares the entire executable byte for byte. Original data copied into an
export cannot conceal changed compiled constants.

## Verification

`DECOMP_TEST_PSX_CPP=1 python -m pytest tests/test_psx.py tests/test_psx_cpp.py`
requires both pinned compilers, MIPS binutils and m2c. Required Windows/Linux CI
fails on skipped tests. Coverage includes original Linux code/relocation golden
files, real C++ features, C rejection of the C++ fixture, invalid C++ errors,
`mipsel-gcc-c++` drafts, all 13 C-built Demo Quest functions matched as C++,
negative instruction/call/GP/table tests, and clean C/C++ exports with per-unit
headers, paths containing spaces and Git `core.autocrlf=true`.

The [native compiler build and parity run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39326290620)
verifies both versions on Windows Server 2022 and Ubuntu 24.04 x86-64 before
publishing their binary/source packages. Its Windows checks run with only
Windows' System32 on PATH, exercise floating-point literals as well as C++
features, and verify propagation of frontend errors.

The [Windows/Linux integration workflow](https://github.com/OMGitsMatt45/decomp.wtf/actions/workflows/windows.yml)
requires all 26 PS1 tests with no skips on both native operating systems. It also
checks that changed owned tables and initialized small data fail in exported
full builds, even when the original data remains in the assembly. Native Windows
matching and exported rebuilds run without WSL, MSYS or Cygwin on PATH.
