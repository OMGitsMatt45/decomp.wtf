# DS settings and data cheats

Generated DS players open **Game settings → Cheats** with F1. Gameplay pauses
while settings own keyboard/mouse input. Arrow keys select a row, Enter or
Space toggles it, and Escape returns. Cheats start disabled each launch.
Values already granted can remain in the cartridge save after disabling them.

The generic exporter ships no retail cheat addresses. A game project may add
`cheats.txt` beside its `assets` directory, or select a catalog with
`--cheats PATH`. Each catalog is bound to the SHA-256 of the exact staged ROM
(the manifest's `asset_sha256`, including any secure-area normalization).

For example, an original program with data at these addresses could use:

```text
rom <64 lowercase hexadecimal SHA-256 characters>
cheat "Example counter"
when16 0x02010000 1 100
write32 0x02010004 42
end
cheat "Example copy"
copy16 0x02010000 0x02010008
end
```

`write8`, `write16`, and `write32` write an unsigned value to aligned main RAM.
`copy16 SOURCE DESTINATION` copies a halfword. Every `when16 ADDRESS MIN MAX`
guard in an entry must pass before that entry writes anything. Guards are
inclusive. Values can be decimal or hexadecimal with a `0x` prefix. Quoted
names are unique and at most 48 characters. Blank lines and full-line `#`
comments are accepted. An invalid catalog fails before the game starts.

Writes that overlap translated function bytes or dispatch-region code are
rejected. Editing an instruction's guest RAM copy cannot change native C++
execution; code-changing cheats need a reviewed native source modification.
This format is for data cheats and does not interpret Action Replay programs.

For reproducible checks, `--enable-cheat "NAME"` enables a named entry from
startup and the JSON report includes enabled and applied-operation counts.
`--settings` opens the menu before gameplay. `--menu-input-script PATH` requires
`--settings` and accepts `frame up|down|enter|back` rows, with zero-based menu
frames. These drive the same navigation handler as keyboard events. A menu
capture is included as `settings.png` when `--capture DIR` is selected.
