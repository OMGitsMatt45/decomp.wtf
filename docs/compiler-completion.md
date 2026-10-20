# Compiler completion record — 2026-10-20

This pass closes gaps in the existing PS2, N64 and Thumb compiler paths before
starting additional platforms. Compiler identity is preserved: a C++ frontend,
a compiler's host implementation language, and the application's implementation
language are separate facts.

| Existing compiler path | Native Windows without WSL | Target source language | Work completed in this pass |
| --- | --- | --- | --- |
| PS2 EE-GCC `2.96-ee-001003-1` | Win32 hosts execute the original x86 compiler instructions | Original C and C++ frontends | Regular pinned installation, complete host source/licenses, exact executable reconstruction, asynchronous `-pipe`, failure propagation and managed-install matching/export checks |
| N64 IDO 5.3 SGI/EDG | Native statically recompiled programs with bundled MSYS runtime DLLs | Original SGI/EDG C++ and original C backend | Existing frontend/backend identity retained |
| N64 IDO 5.3 classic cfront | Same host model as EDG | Original classic C++ frontend and original C backend | Native `ptlink`, cross-unit instantiation, dependency/checksum invalidation, invalid-template rejection and linking of instantiated calls; Windows/Linux verified; regular pinned installation and a reusable N64 prelink command |
| N64 IDO 7.1 | Native statically recompiled programs with bundled runtime DLLs | Original C and SGI/EDG C++ | Existing version-specific integration retained |
| N64 KMC GCC 2.7.2 | Native source port | Original C/C++ | Existing integration retained |
| PS1 GCC 2.7.2 / 2.8.1 | Native source ports with compatible pinned assemblers | Each version's original PS1-patched C/C++ | Existing integrations retained |
| GBA normal agbcc | Standalone native PE compiler plus Arm GNU preprocessing/assembly | Original C; separately restored GCC 2.95.3 C++ frontend | Existing normal Thumb backend retained |
| GBA old agbcc | Standalone native PE compiler plus Arm GNU preprocessing/assembly | Original old C; separately restored C++ frontend | Separate `old_agbcc-cpp`, all objects rebuilt with `OLD_COMPILER`, explicit `agbcc_variant = "old"`, native Windows/Linux code and relocation parity |
| GameCube/Wii/DS CodeWarrior | Existing upstream Windows executables, subject to their explicit license installation | Existing project C/C++ pipelines | No compiler host port added in this pass |

The KMC Windows host implementation is GNU C++98; the bundled N64 analysis
library is C++17. The EE host glue, IDO generated host programs and agbcc compiler
sources are C. Their ability to compile game C++ does not make their implementations
C++. The application itself still uses Python and web frontend code.

## Verification record

- [PS2 native Windows managed installation](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39490389942):
  27 original-driver parity cases and 16 required matching/export checks, zero
  required skips. Includes large pipes, invalid source, missing headers, paths
  with spaces, no local-root override, and clean C/C++ exports. The compiler runs
  with System32-only PATH. Published templates contain no original ELF payload;
  the installer obtains that from the separately pinned upstream archive.
- [GBA variant package verification](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39489803504):
  normal and old Thumb C++ on native Windows and Linux. Checks classes, templates,
  constructors, references, call/data relocation parity with the corresponding C
  backend, invalid C++ and the application's explicit variant selection.
- [Registered compiler regression run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39491624174)
  checks the normal packages on Windows and Linux, including EDG/classic IDO,
  KMC, PS1 and both GBA variants, plus Linux compile sandboxes.
- [Classic IDO details](ido-cpp.md) and [machine-readable validation](ido53-cfront-validation.json)
  record original-IRIX comparisons and native matching/export checks. The new
  prelink corpus resolves template calls across two callers and a separate
  definition file, rebuilds after a changed definition, and rejects a syntax error.
  Its instantiation C text matches unmodified IRIX cfront byte for byte.

All downloadable additions use immutable commit URLs and SHA-256 pins. IDO keeps
explicit license acceptance. A refresh of an older installation uses
`decompnet toolchain install TOOLCHAIN --force` (plus `--accept-license` for IDO).

## Remaining boundaries and new work

These are recorded separately from completion of the current compiler paths:

| Item | Current boundary / required next work |
| --- | --- |
| Conventional PS2 source rebuild | The exact GNUPro EE 2.96 base source archive is still missing. The available Sony patch is incremental; EE 2.9 and SN 2.95 are different compilers. This does not block the verified original-instruction Windows host. See [source investigation](ps2-cpp-source-search.md). |
| agbcc ARM-mode C++ / Windows host | `gcc_arm` identifies a distinct `2.9-arm-000512` compiler. The upstream Linux archive already ships its C executable, `bin/agbcc_arm`; the Windows bundle contains only the two Thumb C compilers. Adding ARM to the application needs its own pipeline/matching checks, and Windows/C++ needs a separate host/frontend port. Unsupported variant selection fails explicitly. |
| IRIX application executables | Classic `ptlink` now supplies target objects for N64 linking. A complete IRIX executable environment, original `c++patch`/startup processing and IRIX shared-library linking are not supplied by this ROM toolchain. N64 object/ROM linking uses the pinned target GNU linker. |
| Target C++ runtime features | Modern standard libraries, exceptions, RTTI, global dynamic initialization and allocation support cannot be inferred from frontend syntax support. These require the particular game's compatible libraries/startup code. |
| PS2 disc/overlay repacking | Existing exports rebuild and verify the flat payload and original ELF envelope. Repacking whole discs or separate overlays needs a separate format/export implementation. |
| New consoles / assembly-heavy work | No new console importers or compiler identities were added here. Their tools and matching requirements need their own implementation and validation. |

See [PS2](ps2-cpp.md), [IDO](ido-cpp.md), [GBA](gba-cpp.md) and
[PS1](psx-cpp.md) for the tested language dialects, flags and export behavior.
