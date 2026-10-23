# Paused game-specific source recovery

This branch shelves exhaustive source-matching work independently of the generic
PS1 importer/reconstruction implementation in PR #4. The next product milestone
is the [DQ/Pokémon PC-output backend proof](../docs/pc-output.md).

- [Syphon Filter 1, 2 and 3](syphon-filter/README.md): paused; four discs,
  2,162 individually exact matches and all earlier drafts/checkpoints retained.
- [Dragon Warrior VII](dqvii/README.md): exhaustive matching paused; two discs,
  2,636 individually exact matches and reviewed engine/module facts retained.
  DS is the first PC-backend integration target; DQVII is retained for later PS1 work.

Only layouts, target identities, compiler profiles and checkpoint hashes are
committed here. Private ZIPs preserve recovered game source and complete attempt
history outside Git. They accompany the task and are not public PR attachments.
No original discs or BIOS are included in either checkpoint ZIP.

These are partial source-recovery checkpoints, not PC ports or new qualified
complete-disc export snapshots. Do not treat target counts as total game code
coverage or assume matched architectural wrappers are portable C.
