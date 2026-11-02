# ROM-bound native cheat support

Data presets retain the existing `rom`, `cheat`, `when16`, `write8/16/32`,
`copy16` and `end` format. All entries start disabled on each launch. Settings
supports arrows, Page Up/Down and Home/End for larger catalogs. An optional
`group "name"` makes entries mutually exclusive; data grants remain after
disabling, while compiled instruction selections are removed before the next
guest step.

The exporter accepts `pc nds-native ... --instruction-choices reviewed.json`.
The reviewed file uses schema `decomp.wtf.nds-instruction-choices/v1`, the exact
original `input_sha256`, and a `sites` array. Each site specifies `cpu`, numeric
`module` (`-1` for main), `address`, `width`, `thumb`, `original` and `values`.
Original decoded bytes, instruction boundaries and supported alternatives are
validated during export. New backward checkpoints and unresolved continuations
are rejected. Every accepted alternative becomes a C++ case in the translated
function. PC-relative literal reads can select a reviewed literal through the
same table. There is no runtime instruction decoder or compiler, and original
guest code, module hashes and function lookup identities remain unchanged.

The generated profile configures a per-machine selection table. Hosts use
`select_instruction_choice(index, value, owner)` and
`clear_instruction_choices(owner)`. Values outside the compiled table and zero
owners are rejected; selecting the original value restores default execution.
Selections are isolated between machines and survive guest resets while their
host owner remains enabled. The manifest records the table SHA-256 and counts.

Catalogs can bind that table with `choices SHA256` after the ROM line, and add
`ar 0xCOMMAND 0xVALUE` rows inside an entry. This bounded memory protocol supports
width-specific writes, comparisons/masks, pointer offsets, counted loops,
data-register loads/stores and inline data payloads. It does not execute CPU
payloads. Unsupported operations and truncated payloads fail catalog loading.
Each program is limited to 65,536 steps and 65,536 written bytes per application.

The host plans a whole program before committing. Reads use the selected
instruction view; actual code bytes stay original. Code writes must resolve to
an allowed compiled selection. Other changed bytes must be in main RAM data,
outside translated functions and protected dispatch regions. Invalid pointers,
uncompiled values and exhausted budgets discard the complete transaction.
Identical data bytes need no write. Key comparisons may read the two DS key
registers. Programs can run before the first guest step for startup patches.

`action "backlight"` provides a native equivalent of a DS Lite brightness
payload: L+R+Select with Up/Down changes four game-window brightness levels.
It affects presentation only; no operating-system brightness or guest code is
changed. Turning it off restores normal brightness.

Synthetic native tests cover real alternative execution, previously unreachable
fallthrough, literal reads, original code bytes, owner cleanup before a guest
step, per-machine isolation, guards, masks, loops, offsets, skipped payloads,
transaction rollback, budgets, group exclusion and rejected policy identities.

Protocol behavior was checked against the primary
[melonDS command implementation](https://github.com/melonDS-emu/melonDS/blob/master/src/AREngine.cpp).
The memory planner and native selection adapter here are independently authored.
