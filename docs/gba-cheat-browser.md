# Native game cheat browser

Desktop GBA exports open a browser inside the game window with F1/Escape or
`--settings`. Arrows select a preset and category; GBA A toggles, B/Start returns,
L/R pages and Select disables all cheats. Existing custom code entry remains
available on Windows through F2. The game and audio pause while the browser is
open. Held close buttons are suppressed until released when gameplay resumes.

Projects can register `CheatPreset` entries and an optional context probe through
`game_cheat_catalog().configure(...)` in `custom/game.cpp`. When the probe reports
the game's menu is ready, the player shows a shortcut and GBA R opens the browser.
The generic frontend contains no game-specific addresses or built-in game codes.

Presets default off. Stable IDs are saved beside the selected save in
`.preset-picks`; manual device codes keep their existing `.cheats.toml` file.
Presets in the same nonempty group are mutually exclusive. Invalid or incompatible
entries remain visible with an explanation and cannot silently become active.
Persistence failures restore the previous selection. Turning a cheat off stops
its future effects; it does not undo items or stats subsequently saved in game.

The catalog normally executes compiled RAM-only cheat programs at frame boundaries.
An optional filter can restrict those writes to appropriate game states. Entries
marked `project_applied` are applied by the project at a safe point instead.

Instruction-patching device codes remain rejected by the native player. A project
may implement an equivalent with `System::set_native_entry_hook(address, thumb,
callback)`. The callback runs before a compiled ROM entry, including direct native
calls. Returning false continues the original body with any adjusted arguments;
returning true skips it. A replacement must leave the guest registers, mode, PC and
cycle budget consistent with its guest ABI. Use this API for compiled code only;
it does not change the explicit reference interpreter. Removing the last hook
disables the entry check, and a project can set `cpu().native_hooks` to zero while
its registered hooks are inactive. The flag survives reset.

The browser's bitmap is represented as a synthetic GBA mode-3 scene and uses the
same GPU renderer. No game VRAM or game graphics registers are changed. Regression
coverage includes three bitmap sizes with a pixel-varying pattern, eighteen
original hardware scenes, native argument/replacement hooks, reset, RAM mirrors,
exclusive choices, preference reload, all-off behavior and failed persistence.

For reproducible player qualification, `--menu-input-script FILE` supplies the
same frame/mask format as `--input-script`, counted in presented menu frames.
Each opening starts at frame zero; B/Start returns to the game. If the script
ends without returning, two trailing menu frames are retained and the player
closes cleanly. The report records menu openings/frames and enabled preset count.
This tests the actual browser/controller/renderer without OS keyboard injection.

The scanline scene (over 560 KiB) is allocated on the heap only for desktop
presentation. Keeping it in the player's `main` stack frame exhausted the default
1 MiB Windows stack during a large project's initialization. The retail one-frame
startup reproducer failed with `0xC00000FD` before this change and succeeds with
zero interpreted cycles after it; the headless path does not allocate the scene.
