# Matching PlayStation (PS1) code

CPU: MIPS R3000A (MIPS I). Things that look odd at first:
- Load delay slot: the instruction after a load can't use the loaded value; you'll see `nop`s or
  reordering there. Branch delay slots exist too; there's no branch-likely.
- `mult`/`div` put results in HI/LO (`mflo`, `mfhi`). Division is followed by checks for divide by zero
  (`break 7`) and overflow (`break 6`). Their exact sequence depends on the assembler; public projects
  may use maspsx to reproduce a specific Sony ASPSX version. Inspect the pinned project build.
- `$gp`-relative small data (-G4 or -G8): small globals are read with `lw $v0, %gp_rel(sym)($gp)`
  (one instruction) instead of `lui` + `lw`. In a ROM project, declare such globals in context.h
  *without* `extern` (`s32 D_8001B278;`): the compiler then treats them as small data. With `extern`
  it builds the full address and the function won't match. Arrays and structs larger than the limit
  are never gp-relative.

Compilers: PSY-Q SDK GCC 2.6/2.7.2/2.8.x and ASPSX versions differ in register allocation and
instruction scheduling; the project picks them per file. Public decomp projects retain their own toolchain.
ROM projects using `gcc-2.7.2-psx` or `gcc-2.8.1-psx` default to genuine C++ drafts and `.cpp` exports
with the original version's C++ frontend. Plain game functions and extern declarations retain C linkage;
use explicit `extern "C++"` for overloaded helpers. Templates and classes keep their C++ linkage.
An explicit `compiler.language = "c"` retains C.

The dialect is the period GNU C++ language, not modern C++. Exceptions and RTTI are disabled; no
standard library or C++ runtime/startup implementation is supplied. Use `0` for a null pointer instead
of C's `(void *)0`. Equivalent C++ expressions may produce different instructions: adjust the candidate
while preserving exact byte and relocation matching. PS1 builds use `-fconserve-space` so small-global
context declarations keep C-style common storage across exported translation units.

ROM projects use pinned GNU assemblers: binutils 2.6 with GCC 2.7.2 and compatible MIPS binutils v0.10
with GCC 2.8.1. This does not emulate every ASPSX version; never assume division or scheduling matches
merely because the compiler version is similar. Exports validate instructions, resolved relocations
and owned constants before linking and compare the entire executable byte for byte.

Libraries: PSY-Q's libgte, libgpu, libgs, libspu, libcd, libetc, libapi and libc are usually linked
as library objects, not decompiled; their names and prototypes are in the project's headers.

GTE (the geometry coprocessor): `mtc2`/`mfc2`/`ctc2`/`cfc2`, `lwc2`/`swc2` and commands like
`RTPS`/`NCLIP` come from PSY-Q's GTE macros (`gte_ldv0`, `gte_rtps`...). Use the project's macros;
don't write raw assembly.

Typical patterns: `jtbl_` jump tables in .rodata for dense switches; overlays loaded at the same address
(separate units); `D_800xxxxx` data and `func_800xxxxx` names for things nobody named yet.

Disc imports retain eligible ISO/raw-sector images for exact full-disc exports. The source view states
whether the complete disc or only program payloads can be rebuilt. Raw-overlay addresses are inferred
from absolute calls; review them against the game's loader. PS-X EXE overlays use their explicit load
headers. Shared RAM does not mean shared claims or targets: select the module-qualified function name.
Matching builds keep file sizes, sectors and addresses fixed. CHD recompression, CUE authoring,
runtime relocation and custom/compressed overlay containers need separate support.
