# Nintendo DS: encrypted imports and reconstruction qualification

Status: **draft implementation; first qualification phase**. Baseline: current `main`.

PR #7 now preserves PR #1's implementation commit and integrates it with the
current import paths and native Windows/Linux checks. PR #1's branch and review
history remain available. Keep PR #7 in draft while the remaining gaps below
are unresolved.

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
same decryption check when rebuilding.

The full-image check still compares every byte, with the existing explicit
trimmed/padded-tail policy. Secure-area prefix and checksum differences are never
exempted. A failed recheck removes any old success stamp.

## Existing programs to reuse or qualify

Uses pinned dsd 0.12.1, native Windows CodeWarrior tools, wibo on Linux, objdiff
and m2c. No compiler version is substituted. Original fixtures qualify
CodeWarrior DS 2.0/sp1p5 and 2.0/sp1p6; mode-wrapper checks compile both C and C++.

## Original-fixture validation

The committed fixture generator encrypts our own Demo Quest DS with generated
test data. It contains no Nintendo BIOS code or console key table. It includes
an ARM-to-Thumb call, ARM9 ITCM/DTCM autoloads, two ARM9 overlays sharing a runtime
address, unused overlay data, and an ARM7 overlay retained as original data.

The DS suites check:

- Missing/wrong BIOS errors and successful encrypted imports through the
  authenticated browser API; failed imports leave no registered project or BIOS.
- Private BIOS exclusion from Git and reuse after removing generated build and
  extraction output in a standalone copy with spaces in its path.
- Exact whole-ROM rebuilds, module hashes and symbol addresses; scoped matches
  in both overlapping overlays and a real Thumb function match.
- ARM/Thumb push/pop restoration in C and C++, plus rejection of changed secure
  prefixes and checksums without retaining an old verification stamp.

After installing the development dependencies and registered DS tools and
building `projects/demo-ds/build.py`, run:

```sh
uv run pytest -q tests/test_ds.py tests/test_ds_rom_check.py tests/test_ds_bios.py tests/test_ds_units.py tests/test_ds_modes.py tests/test_ds_encrypted.py
```

The full operational coverage gate requires these suites on Windows and Linux;
missing compiler prerequisites must not silently count as passing coverage.

## Work that remains

- [x] Review and preserve PR #1's private BIOS, overlapping-entry, word-alignment, unused-section and instruction-mode changes on current main.
- [ ] Resolve the reported secure-prefix/checksum rebuild differences without masking bytes or weakening the whole-ROM comparison.
- [ ] Expand ARM7, ARM9, autoload and overlay coverage, including runtime-loaded modules and compiler-version differences.

The original YV5P retail-ROM case from PR #1 has not been rerun: this phase uses
original test fixtures. A valid fixture rebuild does not establish that its
reported 12 differing bytes are resolved. Nonstandard secure-area prefixes are
rejected explicitly. The pinned toolkit also rounds some overlay BSS extents to
32 bytes; nonstandard extents can still fail the strict ROM check.

ARM7 programs and ARM7 overlays are retained, not recovered as matching C/C++.
The generated DS template compiles candidate source for object comparison but
does not yet automatically link recovered source units into the ROM. Exact
round trips currently use the retained original objects. Further runtime-module,
DS Protect, compiler-version and linked-source coverage remains open.

## Acceptance checks

- [x] Integrate PR #1 without rewriting its history and rerun its focused tests on current main.
- [x] Use legal original encrypted/unencrypted fixtures and confirm test keys stay in ignored private paths.
- [x] Verify module checks, symbol addresses, restored ARM/Thumb mode and a strict full-ROM rebuild on those fixtures; retain failures as failures.
- [x] Add browser imports, claims, failure reporting and clean standalone rebuild coverage for encrypted projects.
- [ ] Qualify the bounded pilot CLI with encrypted inputs on both native hosts.
- [ ] Keep current required operational suites passing; new platform checks must fail rather than silently skip missing required tools.

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
