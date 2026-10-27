# Roadmap

The shared native-PC-output milestone is implemented for **Nintendo DS,
PlayStation, PlayStation 2, Game Boy Advance and Nintendo 3DS**. Each backend
exports an editable game project with runtime source, asset preparation, pinned
build dependencies and host-build instructions. Compatibility is established per
game; the milestone does not certify every ROM or a complete playthrough.

## Implemented on main

| Area | Current result | Implementation and evidence |
| --- | --- | --- |
| Shared application | Separate native PC export from console reconstruction; preserve input identities, source hashes, build targets and execution reports | [PC contract](pc-output.md), [#28](https://github.com/OMGitsMatt45/decomp.wtf/pull/28) |
| DS | ARM9/ARM7 and overlays; GPU rendering, original dual screens, audio, input, cartridge saves and local RTC | [Guide](nds-native-runtime.md), [#29](https://github.com/OMGitsMatt45/decomp.wtf/pull/29), [#36](https://github.com/OMGitsMatt45/decomp.wtf/pull/36), [#38](https://github.com/OMGitsMatt45/decomp.wtf/pull/38) |
| PS1 | One project/executable for ordered discs; adaptive OpenGL, shared memory cards and normal execution without interpreter fallback | [Guide](ps1-native.md), [validation](ps1-native-validation.json), [#30](https://github.com/OMGitsMatt45/decomp.wtf/pull/30), [#40](https://github.com/OMGitsMatt45/decomp.wtf/pull/40) |
| PS2 | Translated EE, IOP and vector operations; Vulkan geometry, disc/media services, input, audio and saves | [Guide](future/ps2.md), [validation](ps2-native-validation.json), [#5](https://github.com/OMGitsMatt45/decomp.wtf/pull/5), [#31](https://github.com/OMGitsMatt45/decomp.wtf/pull/31), [#32](https://github.com/OMGitsMatt45/decomp.wtf/pull/32), [#41](https://github.com/OMGitsMatt45/decomp.wtf/pull/41) |
| GBA | ARM/Thumb, guarded RAM copies and optional compiled BIOS; adaptive OpenGL, audio, controls, saves and RTC | [Guide](future/gba.md), [Emerald validation](gba-static-validation.json), [#6](https://github.com/OMGitsMatt45/decomp.wtf/pull/6), [#39](https://github.com/OMGitsMatt45/decomp.wtf/pull/39) |
| 3DS | Decrypted images, ARM/Thumb/VFP and CRO/CRS; source runtime, Vulkan, original dual screens, audio, input and saves | [Guide](3ds-native.md), [physical GPU record](3ds-hardware-validation.json), [#34](https://github.com/OMGitsMatt45/decomp.wtf/pull/34), [#37](https://github.com/OMGitsMatt45/decomp.wtf/pull/37) |

The final PS2 integration passed all nine qualification workflows on its tested
head before [#41 merged](https://github.com/OMGitsMatt45/decomp.wtf/pull/41).
Its original Windows/Linux checks include 64 native/reference vector comparisons,
changed-code rejection and 412 reference-runtime cases. The bounded DQVIII boot
ran 600 frames without interpreted instructions or coverage misses. That path
executes no vector microprograms; original fixtures establish vector execution.
Full playthrough acceptance remains with the user.

## Work after the shared milestone

- Validate complete playthroughs and fix concrete per-game coverage, layout or
  platform-service problems found in them. Keep profiles tied to exact inputs.
- Customize exported projects with game-specific camera layouts, mobile assets,
  interpolation, settings or other enhancements. DS/3DS screen merging is not
  a generic application option.
- Keep host builds, source integrity, input ownership and execution evidence
  distinct. Explicit reference/diagnostic modes do not qualify native gameplay.
- Evaluate additional consoles when work on them is requested. The older
  [planning PRs](pr-scope-audit.md#deferred-console-proposals) retain those ideas;
  they are not current application support or active implementation blockers.

## Preserved work and history

[PR #27](https://github.com/OMGitsMatt45/decomp.wtf/pull/27) preserves the previous
matching/reconstruction application at an identical Git tree.
[PR #26](https://github.com/OMGitsMatt45/decomp.wtf/pull/26) preserves paused
DQVII and Syphon Filter source-recovery checkpoints; private source stays private.
The separate [DSi foundation #24](https://github.com/OMGitsMatt45/decomp.wtf/pull/24)
is deferred container-inspection work, not a sixth native backend.

GB/GBC, N64, GameCube and Wii functionality is removed from the current product;
its history remains in Git. The [current PR index](pr-scope-audit.md) distinguishes
implemented work, superseded plans and preservation drafts. The original
[2026-10-23 migration audit](history/pr-migration-2026-10-23.md) is retained as a
historical snapshot.
