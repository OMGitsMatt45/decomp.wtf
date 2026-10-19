# GBA C++ game output

GBA ROM projects using `agbcc` default to real C++ for drafts, compilation,
matching and exported projects on Windows x86-64 and Linux x86-64. Exported
functions use `.cpp`. Existing exports without a language field still build as C;
an explicit `compiler.language = "c"` also preserves C compilation.

## Compiler identity

The original pret package contains C frontends only. decomp.wtf adds a **separate
`agbcc-cpp` executable**: the GNU GCC 2.95.3 C++ frontend restored against
pret/agbcc's existing Thumb backend. This is a frontend extension, not an original
Nintendo C++ compiler binary. It does not replace agbcc's backend with modern GCC
or claim that every unchanged C expression will produce identical C++ output.

| Component | Pinned source / role |
| :-- | :-- |
| Original C compiler | Existing pret Linux release / native Windows package, unchanged |
| C++ language frontend | GCC 2.95.3, `7f236610e99c7a11fb18f056b6446b3c7c40979c` |
| Thumb backend | pret/agbcc, `da598c1d918402c42c0c0d7128ba14567f3175e9` |
| Preprocessing and assembly | Pinned Arm GNU 14.3.Rel1 `cpp` and `as` |
| Export linking | The same Arm GNU toolchain, followed by full ROM comparison |

The port restores language hooks for C++ declarations, templates, inline
emission, attributes, constants and weak symbols. Backend instruction selection,
optimization and register allocation remain agbcc's. The Python pipeline invokes
each native executable directly. Windows needs no WSL, MSYS or Cygwin runtime.
The build uses MinGW on Linux to produce the standalone Windows executable.

Immutable, SHA-256-pinned packages include complete corresponding GPL sources,
licenses, patches and the build recipe in `cpp-source/`. See
[`tools/gba_cpp`](../tools/gba_cpp) and the
[verified binary/source packages](https://github.com/OMGitsMatt45/decomp.wtf/tree/05b4893dcded97f392aa1e999855d7c0bc4bf8aa/toolchains/gba-cpp).
Reinstall an older toolchain with:

```sh
decompnet toolchain install agbcc --force
```

## Language and matching

This is the GCC 2.95-era C++ dialect: templates, classes, local constructors,
references and overloaded helpers are available. Exceptions and RTTI are disabled
by default. No modern C++ standard library or GBA C++ runtime/startup library is
provided. Code requiring `new`/`delete`, exception handling, global dynamic
initializers or other runtime support needs the game's compatible implementation;
this conversion does not establish that support. ARM-mode and `old_agbcc` C++
frontends are not included; the restored frontend targets the normal agbcc Thumb
pipeline.

Plain game functions, prototypes and external variables retain C linkage.
Classes, templates, static helpers and explicit `extern "C++"` declarations keep
their authored linkage. Judge and exported builds apply the same linkage rules.
Per-unit headers are exported with their functions.

C++ syntax can change the generated code. In the demo, replacing
`!(e->flags & ENTITY_FLAG_ACTIVE)` with
`(e->flags & ENTITY_FLAG_ACTIVE) == 0` preserves the C game's instructions;
the negated expression generates different code in C++. C's `(void *)0` null
macro must become `0` in a C++ context. These are explicit source/context changes,
not automatic rewrites of submitted function bodies.

Matching still requires original instruction bytes, resolved call/data
relocations and owned ROM data. Every export checks each matched function again;
failures are reported as assembly fallbacks. Every exported `build.py` also
performs those strict checks before linking and compares the entire rebuilt ROM
byte for byte. Changing compiled constants cannot pass because original ROM data
was copied into gaps in the output.

## Verification

Required Windows and Linux CI tests use the pinned release packages and official
Arm GNU suite. They fail if the integration tests are skipped. Coverage includes:

- Actual C++ templates, classes, local constructors and references, with C byte
  and relocation parity; C rejects the same C++ source and invalid C++ is rejected.
- An m2c `gba-gcc-c++` draft compiled and matched against a C-built target.
- Rejection of wrong instructions, wrong relocation destinations and changed
  owned constant data.
- All 13 game functions in the homemade Demo Quest GBA C-built ROM matched as
  C++, including a template class implementation of `abs_s32`.
- `.cpp` exports with C symbol linkage and per-unit headers; clean rebuilds with
  no assembly/build cache, paths containing spaces and Git `core.autocrlf=true`.
- Exported builds rejecting changed code and wrong call targets, and legacy C
  exports continuing to rebuild without a language field.

This validates the supported pipeline on a redistributable test game. It does
not guarantee that arbitrary commercial ROM functions already match as C++.
