# Original DS static execution fixture

`arm9.s` and `arm7.s` are original CC0 test code. They contain no retail game,
SDK or BIOS code. `program.json` records the assembled bytes and symbol locations
used by `tests/fixtures/nds_static.py`; literal pools are excluded from reviewed
instruction ranges.

The program communicates through main RAM, calls Thumb code, replaces two
overlays at one address and updates a RAM checkpoint. Its overlay loader also
has a real original ARM implementation for independent CPU-oracle execution.

Regenerate `program.json` with an installed ARM GNU toolchain:

```sh
uv run python tools/make_nds_static_fixture.py
```

Normal tests and generated PC repositories use the committed encodings and do
not need that console toolchain. The separate arithmetic/shift fixtures are
original instruction encodings in `nds_static.py` and need no assembler.
