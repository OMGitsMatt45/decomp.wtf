# Dragon Warrior VII recovery checkpoint

Exhaustive original-compiler matching is **paused**. DQVII remains the first
target for a PC-project backend; targeted source recovery can resume when a
specific loader/runtime failure needs it. Achieving 100% byte-matching C/C++ is
not a prerequisite for static recompilation.

The authoritative two-disc checkpoint retains:

| Disc | Serial | Current targets | Individually exact matches |
| --- | --- | ---: | ---: |
| 1 | SLUS-01206 | 4,679 | 1,322 |
| 2 | SLUS-01346 | 4,679 | 1,314 |

This includes the earlier boot recovery and additive reviewed field/battle
engines plus nine VRAM-cached CPU modules. The final bounded runtime pass saved
490 new exact sources and 490 independently judged cross-disc transfers, with
zero recorded errors; interruption was acknowledged and all claims released.
The original images and historical qualified complete-disc exports remain
untouched. These newer matches have not received a fresh full export/ZIP
qualification and do not establish game execution or a PC port.

The public files contain only the disc/target/source hashes, reviewed module
layouts and effective compiler profile metadata. The private checkpoint ZIP
contains a consistent backup of the final recovery database, project files,
contexts, recovered source, unsuccessful drafts/attempts, runtime recovery
checkpoint and script, engine-import/boundary backups and loader evidence.
Original disc images, BIOS/SDK payloads and older large export ZIPs are excluded;
their existing private copies remain available separately.

Verify the accompanying private ZIP without modifying or extracting it:

```sh
python tools/verify_recovery_checkpoint.py /path/to/dqvii-recovery-2026-10-23.zip \
  --checkpoint recovery/dqvii/checkpoint.json
```

Preserve the ZIP and extract only into a new private directory. Inspect its
`INDEX.json`; `databases/reviewed.db` is authoritative. As with the
[Syphon Filter checkpoint](../syphon-filter/README.md#verify-and-resume), database
roots/configuration retain original workspace paths and require review before
relocation. Use the exact original disc hashes, compiler profiles, contexts and
the full compile/link judge before accepting further source matches.

The next milestone is a pinned backend proof with an original fixture, followed
by a single Windows-buildable DQVII project using both ordered discs. See the
[PC-output scope](../../docs/pc-output.md) for acceptance criteria and the
unqualified PSXRecomp candidate.
