# Nintendo DS: encrypted imports and reconstruction qualification

Status: **ready for review on original fixtures; individual retail qualification remains open**.
Baseline: current `main`.

PR #7 now preserves PR #1's implementation commit and integrates it with the
current import paths and native Windows/Linux checks. PR #1's branch and review
history remain available. The agreed qualification uses original fixtures;
individual retail cases and further recovery features remain explicit below.

## Current coverage

Generated ds-decomp projects support ARM9 C/C++ object matching, including
autoloads and overlays. This phase adds private ARM7 BIOS handling for encrypted
imports, overlapping-entry and aligned source-unit fixes, retention of unused
original sections, and function-local ARM/Thumb mode wrappers for machine drafts.

Set `DECOMP_ARM7_BIOS` before starting the app, or pass `--arm7-bios` to
`tools/ds_pilot.py`. The supplied 16 KiB file is copied to ignored
`extract/arm7_bios.bin`, reused by standalone builds, and restricted to owner
access on POSIX hosts. Private paths are ignored before the first extraction or
build. Missing keys and failed secure-area decryption stop the import before any
matching targets are registered. The generated project's extractor applies the
same decryption check when rebuilding, stages output separately, and preserves
the previous verified extraction after a failure.
BIOS copies are owner-only while being written and replace the retained copy
only after completion; interrupted copies leave no partial key file.
Generated builds use the key when the input is encrypted or retains an encrypted
secure-area checksum. Unencrypted homebrew with a zero checksum omits it, so a
globally configured BIOS cannot change otherwise identical header bytes. This
choice persists in clean standalone builds.

Finished ARM9, autoload and overlay source units replace their original objects
only after all their code/data match and the complete ROM still verifies.
The existing link workflow now uses ds-decomp's `complete` markers and rolls
back configuration changes after failed or interrupted verification. Linked
source edits must keep the full ROM identical. Unfinished units retain their
original objects.

The full-image check still compares every byte, with the existing explicit
trimmed/padded-tail policy. Secure-area prefix and checksum differences are never
exempted. A failed recheck removes any old success stamp.

## Existing programs to reuse or qualify

Uses pinned dsd 0.12.1, native Windows CodeWarrior tools, wibo on Linux, objdiff
and m2c. No compiler version is substituted. Original fixtures qualify
CodeWarrior DS 2.0/sp1p5 and 2.0/sp1p6; mode-wrapper checks compile both C and C++.
Additional encrypted source-link checks exercise all 22 other registered versions
(DS 1.2, DS 2.0 and DSi-branded compilers) using an ordinary DS container.
DSi-enhanced/exclusive containers are rejected before querying compilers or
creating projects. The pinned ds-rom builder explicitly does not preserve their
ARM9i/ARM7i programs and authentication metadata; supplying DSi BIOS files cannot
add that missing support.

## Original-fixture validation

The committed fixture generator encrypts our own Demo Quest DS with generated
test data. It contains no Nintendo BIOS code or console key table. It includes
an ARM-to-Thumb call, ARM9 ITCM/DTCM autoloads, two ARM9 overlays sharing a runtime
address, unused overlay data, and an ARM7 overlay retained as original data.
The original ARM7 program advances a separate shared-RAM counter, so runtime
qualification can observe both processors.

The DS suites check:

- Missing/wrong BIOS errors and successful encrypted imports through the
  authenticated browser API; failed imports leave no registered project or BIOS.
- Private BIOS exclusion from Git and reuse after removing generated build and
  extraction output in a standalone copy with spaces in its path.
- Exact whole-ROM rebuilds, module hashes and symbol addresses; scoped matches
  in both overlapping overlays and a real Thumb function match.
- ARM/Thumb push/pop restoration in C and C++, plus rejection of changed secure
  prefixes and checksums without retaining an old verification stamp.
- C and genuine C++ source linking on both compiler versions, rejection of
  changed linked code, and configuration rollback after a linker exception.
- Verified source linking for the main ARM9 Thumb program and ITCM autoload,
  alongside overlapping-overlay source linking.
- Compressed ARM9 programs and ARM9/ARM7 overlays, including linked-source
  recompression, rejection of changed code, and clean standalone rebuilds.
- The bounded CLI finishes source linking synchronously and records its result
  before exiting, with a completed source-linked project verified on both compilers.
- Unencrypted imports with a configured BIOS, both with zero secure checksums
  and with retained encrypted checksums, including clean standalone rebuilds.
- Overlay BSS sizes of 0, 4, 20 and 36 bytes. The build derives these extents from
  linked boundary symbols without ds-decomp 0.12.1's extra 32-byte rounding;
  deliberate linked BSS changes still fail the complete-ROM check.
- An additional runtime autoload at 0x02280000, with and without BSS, linked from
  matching C source on both primary compiler versions.
- Encrypted import, real source matching/linking and exact whole-ROM rebuilding
  across all 24 registered compiler versions.
- Early rejection of DSi containers, including inconsistent DS/TWL flags.

After installing the development dependencies and registered DS tools and
building `projects/demo-ds/build.py`, run:

```sh
uv run pytest -q tests/test_ds.py tests/test_ds_rom_check.py tests/test_ds_bios.py tests/test_ds_units.py tests/test_ds_modes.py tests/test_ds_encrypted.py tests/test_ds_inputs.py tests/test_objdiff_errors.py
```

The full operational coverage gate requires these suites on Windows and Linux;
missing compiler prerequisites must not silently count as passing coverage.
The focused `Nintendo DS native qualification` workflow runs the same DS suites
on both hosts for quicker feedback, with an independent gate that rejects
missing suites and skipped cases.

The [native qualification](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39732285590)
at [`fcbb03e`](https://github.com/OMGitsMatt45/decomp.wtf/commit/fcbb03e2a2d6da22f9114118127e0d46e8d52cc6)
passes **112 import/matching/rebuild checks and 3 execution checks on each host,
with zero skips**. The dedicated execution jobs build and run native Linux and
Windows cores, using their built-in replacements rather than private inputs.
The [full application run](https://github.com/OMGitsMatt45/decomp.wtf/actions/runs/39732278706)
passes all seven jobs: Linux core 617 passed plus 5 separate i386 checks;
Windows core 591 passed. Its 33/59 platform/private-ROM or separately scheduled
skips are separate from required suites, which have none. Those totals include
the three execution cases required by the dedicated native jobs above.

An additional private local run passes all **71 encrypted-workflow checks** with
the supplied ARM7 BIOS. Using the supplied ARM9 BIOS and firmware, direct boot
produces identical watched state over 120 frames for the original demo, its
encrypted fixture and source-linked Thumb rebuilds from both primary compilers.
The ARM9 counter advances from 256 to 10,000 and the ARM7 counter from 162,635 to
2,150,406 between sampled checkpoints. The supplied files remain outside Git;
CI contains only original fixtures and generated test keys.

## Execution validation

`tools/ds_boot.py` compares execution of the original Demo Quest DS and its
rebuilt copies, using a separately installed
[melonDS libretro core](https://github.com/libretro/melonDS). It accepts your own
`bios7.bin`, `bios9.bin` and `firmware.bin`. A core can also be obtained through
[RetroArch's core downloader](https://www.retroarch.com/?page=platforms).
These optional developer tools and runtime files are not part of app installation.
On Linux, source qualification used libretro/melonDS commit
`66b5d2634cd0a79030562811e6e05f5532f800ba`, built with:

```sh
make -j4 HAVE_OPENGL=0 HAVE_WIFI=0 LIBS='-lm -lpthread -lrt'
```

After building the original fixture and making a source-linked rebuild, run:

```sh
uv run python tools/ds_boot.py --core /path/to/melonds_libretro.so --bios-dir /path/to/your/ds-runtime-files --symbols projects/demo-ds/build/demoq_ds.elf --output ds-execution.json projects/demo-ds/build/demoquest.nds /path/to/rebuilt.nds
```

Use the corresponding `.dll` on Windows. The runner copies runtime files to a
private temporary directory, starts a fresh core process for each ROM, disables
JIT, supplies no controller input and compares watched game state over 120
emulated frames. Both the ARM9 game counter and ARM7 shared-RAM counter must
advance. Firmware profile output is captured privately and omitted from reports.
For unencrypted original fixtures, `--builtin-bios` can replace `--bios-dir` to
explicitly select the core's built-in BIOS and firmware replacements. CI builds
the pinned software core and runs a separate execution gate using those
replacements, with no private console files. It verifies a source-linked Thumb
program and rejects independently stalled ARM9 and ARM7 programs. Missing or
skipped execution cases fail that gate.
The original fixture now establishes system mode, separate supervisor/IRQ stacks
and its TCM mappings before calling the BIOS; its previous startup could lose
the caller's banked link register and repeatedly restart.
This is direct-boot CPU execution validation, not physical-console or
firmware-menu certification. The fixture uses a blank logo and simplified
runtime helpers and is intended for decompiler qualification.

## Completed qualification

- [x] Review and preserve PR #1's private BIOS, overlapping-entry, word-alignment, unused-section and instruction-mode changes on current main.
- [x] Reproduce the 12-byte secure-prefix/checksum failure pattern on an original fixture and reject failed decryption before creating matching references, without masking bytes.
- [x] Qualify ARM9/ITCM source linking, DTCM reconstruction, overlapping overlays, ARM7 byte retention, compression and both DS compiler versions on original fixtures.
- [x] Expand ARM7 execution/retention, runtime-autoload and compiler-version coverage on original fixtures.

## Additional compatibility work

- [ ] Verify the original YV5P input with its correct BIOS before claiming its specific reported discrepancy is resolved.
- [ ] Qualify DS Protect variants and implement ARM7 C/C++ source recovery beyond the pinned toolkit's ARM9 analysis.

The original YV5P retail-ROM case from PR #1 has not been rerun: this phase uses
original test fixtures. A wrong test key reproduces exactly 12 changed bytes
with raw dsd: offsets `0x6C-0x6D`, `0x15E-0x15F` and `0x4000-0x4007`. The guard
rejects that failed decryption before it can replace verified reference data.
This establishes one concrete cause of the pattern; it does not establish that
the original YV5P input used a wrong key or that its specific case is resolved.
Nonstandard secure-area prefixes are rejected explicitly. The build corrects the
pinned toolkit's extra overlay BSS rounding using the actual linked boundaries,
without changing the ROM comparison.

ARM7 programs and ARM7 overlays are retained, not recovered as matching C/C++.
Recovered source can enter exact ROM rebuilds once its entire unit matches.
Partial round trips still retain unmatched original objects. Further ARM7,
runtime-module, DS Protect and compiler-version coverage remains open.

## Acceptance checks

- [x] Integrate PR #1 without rewriting its history and rerun its focused tests on current main.
- [x] Use legal original encrypted/unencrypted fixtures and confirm test keys stay in ignored private paths.
- [x] Verify module checks, symbol addresses, restored ARM/Thumb mode and a strict full-ROM rebuild on those fixtures; retain failures as failures.
- [x] Add browser imports, claims, failure reporting and clean standalone rebuild coverage for encrypted projects.
- [x] Qualify the bounded pilot CLI with encrypted inputs on both native hosts.
- [x] Qualify additional runtime autoloads and matching source links across all 24 registered DS compiler versions.
- [x] Execute original/source-linked programs on native Windows/Linux, require both processors to advance and reject independent processor stalls.
- [x] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

## Starting points

- `src/decompnet/forks/scratch_dsd.py`
- `src/decompnet/forks/ds_template/`
- `src/decompnet/forks/drafts.py`
- `tests/test_ds.py`

## References

- [Existing unfinished PR #1](https://github.com/OMGitsMatt45/decomp.wtf/pull/1)
- [ds-decomp](https://github.com/AetiasHax/ds-decomp)

Upstream links are research and reuse candidates, not a claim that current release
binaries support both hosts or reproduce a game's original compiler. Verify version,
license, checksums and actual native execution before registering a tool.

No commercial ROMs, SDK payloads, BIOS files or keys belong in this branch.
See the [main roadmap](https://github.com/OMGitsMatt45/decomp.wtf/blob/main/docs/future-work.md).
