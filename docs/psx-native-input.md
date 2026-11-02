# Native PS1 input checks

The normal keyboard map uses arrows for movement, X/S for Cross/Circle, and
Enter/Right Shift for Start/Select. Held keys follow SDL's physical state.
F9 retains the runtime's fast-forward toggle; F10 cycles to the next disc.
The F1 settings menu accepts both arrow keys and keypad 8/2/4/6 for navigation.

Instantaneous desktop automation taps can be shorter than a game's polling
interval. `--key-tap-frames N` preserves each keyboard pulse for 1–30 guest pad
samples. The default is 1; use 6 for a 100 ms pulse at 60 Hz when driving the
player with an automation API that cannot hold keys. Menus, focus loss, and
per-player input suppression clear pending pulses. This option can merge taps
that arrive closer together than the selected duration.

`--input-script PATH` instead replays `FRAME ACTIVE_LOW_PAD_MASK` rows. Each mask
persists until the next row, including a released `0xffff` row. A `FRAME LIVE`
row releases the scripted mask and returns to live device sampling in the same
process, so a recorded prefix can hand control back without a snapshot reload.
For example, Cross is `0xbfff`.

Set `DECOMP_PSX_TRACE=1` to log keyboard scancodes and changes to the actual P1
SIO buttons, connection state, analog state, and device kind. Diagnostics go to
stderr so redirected runs can be inspected while the player is still running.

Native snapshot resume has not passed functional qualification: a retail image
can restore visually while forward progress stalls. The native player therefore
rejects PSX_LOAD_SLOT and disables the snapshot shortcut. Use ordinary in-game
memory-card saves. The separate reference target keeps its existing behavior;
the LIVE replay handoff supports automation without snapshot transfer.
