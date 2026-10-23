# Syphon Filter recovery checkpoint

Syphon Filter 1, 2 and 3 recovery is **paused** so active retail work can focus
on Dragon Warrior VII. This checkpoint covers four discs, including both SF2
discs. Generic PS1 import, compiler, module and reconstruction fixes remain in
PR #4 because DQVII and other games use them too.

This directory contains reviewed module layouts, per-target identities,
compiler profiles and hashes of retained exact sources. The actual recovered
C/C++, unsuccessful drafts, assembly, databases and review evidence are in the
**private checkpoint ZIP**, not in this public repository. The ZIP accompanies
this task; it is not a GitHub release or PR attachment. Keep it with the original
disc dumps. The checkpoint records its filename, size and SHA-256.

## What is preserved

| Game | Serial | Current targets | Individually exact matches |
| --- | --- | ---: | ---: |
| Syphon Filter 1 | SCUS-94240 | 2,723 | 622 |
| Syphon Filter 2, disc 1 | SCUS-94451 | 3,125 | 629 |
| Syphon Filter 2, disc 2 | SCUS-94492 | 3,103 | 425 |
| Syphon Filter 3 | SCUS-94640 | 3,282 | 486 |

The 2,162 exact matches include architectural compiler wrappers where explicitly
verified; they are not all portable, high-level game code. These expanded
runtime checkpoints have not received a new complete clean-export qualification.
The historical six-disc export qualification in `docs/psx-validation.json`
remains separate. Neither qualification establishes a native PC port.

The private ZIP includes consistent SQLite backups of both the expanded and
earlier boot-only recovery databases, all three games' worker scripts, reports,
manual source drafts and prior boundary backups, both generations of generated
project files, and reviewed loader/copy/data/boundary evidence. Sources that did
not transplant to a changed boundary remain in the earlier database and work
files. Nothing is credited as a match merely because it was archived as data.
Full original discs, BIOS/SDK payloads and earlier large export ZIPs are excluded;
their existing private copies remain untouched.

`*-functions.csv` records all current target identities and source hashes,
including unresolved targets. `*-profiles.json` maps profile IDs to original
compiler settings without machine-specific paths or agent credentials.
`*-layout.json` preserves reviewed module placement and storage aliases.
Profiles and layouts must be used only with the recorded disc/target hashes.

## Verify and resume

Use the Python version required by decomp.wtf:

```sh
python tools/verify_recovery_checkpoint.py /path/to/syphon-filter-recovery-2026-10-23.zip
```

The verifier checks the entire ZIP, its index and every member without extracting
or modifying anything. The ZIP contains private game-derived material; keep it
outside public Git repositories.

To resume later, first verify the ZIP and preserve a copy. Extract into a new
private directory, inspect `INDEX.json`, and open `databases/reviewed.db` as the
authoritative expanded checkpoint. `databases/legacy.db` and `work/` retain
earlier attempts and boundary variants. SQLite backups passed `quick_check` at
capture. Their project roots/configuration retain the original absolute paths;
this is a checkpoint, not an automatically relocated portable export. Restore
the original private workspace paths or review and update those paths before
starting a worker. Supply the exact original discs listed in `checkpoint.json`.

Resume claims through the application, allowing stale claims to expire. Use
the effective function compiler profile and retained context, and require the
full compile/link judge for every new or transferred match. Replaying a layout
alone does not replay reviewed function-boundary migrations; use the saved
database or the archived migration evidence. Never overwrite the active DQVII
database with one of these checkpoints.

Before declaring a new export qualified, rebuild each full disc from clean
sources, verify its independent hash and check the combined SF2 package.
Gameplay and PC-runtime validation are separate work.
