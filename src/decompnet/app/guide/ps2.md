# Matching PlayStation 2 code

CPU: the Emotion Engine (R5900), MIPS III-like with 128-bit registers.
- `lq`/`sq` move 128 bits; MMI instructions (`pcpyld`, `paddw`, `pextlw`...) come from inlined
  memcpy/memset or vector code.
- `mult rd, rs, rt` (three operands) and `madd` exist; `mflo` still appears.
- The FPU is single precision only: `double` arithmetic becomes calls (`__adddf3`, `__muldf3`): if you
  see those, a double was involved (or a literal without `f`).
- 64-bit integer ops (`daddu`, `dsll32`, `ld`/`sd`) mean `long`/`long long` (ee-gcc: `long` is 64-bit).
  GCC writes register moves as `daddu rd, rs, $zero` (a 64-bit move), older code as `addu`/`or`.
- COP2 is VU0 in macro mode (`vadd.xyzw`, `qmfc2`, `qmtc2`): from the SDK's inline VU0 helpers; use the
  project's macros/functions.
- Float compares: `c.lt.s` + `bc1t`/`bc1f`; float to int: `cvt.w.s` + `mfc1`.

Compilers: Sony's ee-gcc 2.9x (most games), Metrowerks for PS2, or SN Systems' compiler; the project
decides per file. C++ is common: old GCC 2.9x mangling (`update__7CPlayerf`) and vtable thunks.
Small data is `$gp`-relative (-G8 typical), so declare externs with their real sizes.

Libraries: Sony's libgraph, libdma, libpad, libcdvd, libkernl, libsd and libvu0 are linked as
libraries; their prototypes are in the project's headers.

ROM projects using `ee-gcc-2.96` default to C++ with the original `2.96-ee-001003-1`
C++ frontend on Linux x86-64. Native Windows 2.96 is unavailable; do not select a
2.9/SN compiler as a fallback. Plain game functions/externs keep C linkage;
classes, templates and explicit `extern "C++"` helpers retain C++ linkage.
`compiler.language = "c"` keeps C. Exceptions/RTTI are disabled, and no C++
standard library or runtime/startup implementation is supplied.

Use `0` instead of C's `(void *)0`. Equivalent C++ expressions can produce
different instructions; for example `(flags & mask) == 0` may match where
`!(flags & mask)` does not. Change the candidate while retaining exact bytes,
resolved relocations and owned-data checks. Exports compile `.cpp` units with
the same frontend and checks, then verify the entire flat payload and rebuilt
main ELF. The original ELF headers/metadata are retained; discs/overlays are
not repacked.
