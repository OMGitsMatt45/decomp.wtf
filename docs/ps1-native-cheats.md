# PS1 native cheats and settings

`decomp pc psx-native disc1.cue disc2.cue output --experimental --cheats owner.cht`
imports an owner's DuckStation-format CHT catalog. The original file is read as
data; it cannot direct tool execution. Unknown properties, unsupported opcodes,
out-of-RAM writes, malformed slides and unbounded programs fail before publication.

The supported subset is 30 (byte write), 80 (halfword write), 90 (32-bit write),
50 (repeated writes with address/value increments), D0 (one following conditional
statement) and A7 (16-bit match/write/restore). Chained D0 conditions are rejected.
Packed halfword fields preserve byte order even at odd addresses. Writes use the
normal RAM bus on the emulation thread after each frame; boot firmware is excluded.

F1 opens **Game settings → Cheats**. Arrow keys select and Enter toggles a row.
The guest and audio pause while settings owns input. Cheats start OFF at launch.
Names with a common backslash prefix form an exclusive group. Data grants can
remain after disabling and can be saved by the game. A7 restores only if live
bytes still equal its patch. Instruction patches likewise restore only their
owned replacement bytes, preserving independently changed or unloaded code.

Instruction-changing choices are compiled ahead of time from each original code
image and the validated write list. Every variant retains the same complete
immutable-footprint guard as original code. Independent options are combined,
exclusive options are separated, and more than 32 combinations per image fail.
There is no interpreter fallback and no runtime guest-code compiler. An unknown
code mutation still stops with a coverage failure. Source generation and original
fixture checks do not certify the meaning or gameplay safety of a third-party code.

The settings menu also inserts another registered disc through the normal CD tray
API, preserving memory cards and resident native code. It does not invent a game
request for the next disc. Automatic title transitions require verified request
state or a title-specific provider.

Developer checks may pass `--cheat INDEX` (zero-based) and `--input-script PATH`.
An input script contains `FRAME ACTIVE_LOW_PAD_MASK`, with decimal frame numbers
and decimal or `0x` masks. A mask persists until another row. Blank lines and `#`
comments are allowed. Reports record cheat applications, changed writes, settings
openings and whether scripted input was active. Frame scripts are offline tests;
they are not end-to-end physical input latency measurements.
