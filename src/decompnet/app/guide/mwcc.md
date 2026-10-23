# Matching CodeWarrior for Nintendo DS

Use the project's pinned DS compiler version and flags. Keep its pragmas for
optimization, scheduling, inlining and string reuse. DS and DSi compiler versions
are separate; inspect the configured version before changing source.

Inlining
- Small functions defined earlier and header inline helpers may be inlined with
  `-inline auto`. Reuse the project's existing helpers and declaration order.
- A call where the target inlines, or an inline expansion where it calls, can
  change register allocation and stack size throughout the function.

ARM and Thumb
- Code is ARM unless a unit selects Thumb. `-interworking` allows calls between
  the two modes. Read the ARM guide before reasoning about instructions.
- ARM callee-saved registers r4-r11 are saved together. Compare register lifetimes,
  expression shape and local declaration order when only registers differ.
- There is no hardware FPU. With `-fp soft`, float operations call helpers such as
  `_fadd`, `_fsub`, `_fmul`, `_fdiv`, `_ffix` and `_fflt`.
- Division may call `_s32_div_f` or `_u32_div_f`, or use the SDK hardware divider.
- Strings/constants use literal pools and read-only data; `-str noreuse` preserves
  separate copies of equal strings. Do not merge them to improve a score.
- Stack differences can come from address-taken locals, struct copies and inlined
  temporaries. Compare actual ARM stack offsets rather than another CPU's ABI.

Types and SDK interfaces
- Preserve the project's typedefs, enum width, C/C++ linkage and struct packing.
- NitroSDK OS_, MI_, GX_, G2_, FS_, SND_, PAD_ and TP_ declarations often already
  exist in the headers. Reuse them instead of inventing prototypes.
- ITCM code and DTCM data have separate placements. ARM7 and ARM9 need their own
  processor identity, compiler settings and memory facts.
- Generated projects may use `func_02001234` and `data_02041480`; retain those names
  or rename them using the project tools. Keep the original source-unit ownership.

A byte match qualifies console reconstruction. Native PC output also requires
an implemented execution backend and runtime; these compiler rules do not supply it.
