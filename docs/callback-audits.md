# Callback preflight

Run `python tools/audit_gba_callbacks.py --rom owner.gba --source EXPORTED_SOURCE
--inventory callbacks.json --report coverage.json` after export and before CMake.
The command exits with status 1 and lists named missing callbacks when a required
entry is absent or registered in the wrong instruction mode. Status 2 indicates
invalid inputs, including ROM identity or alignment errors. Optional review
candidates are reported separately.

Inventories use `decomp.wtf.callback-inventory/v1`, the exact ROM SHA-256, and an
`entries` array with `address`, `mode` (`arm` or `thumb`), optional `name` or
`names`, and optional `required` (defaults to true). Addresses are unsigned,
aligned ROM addresses with the Thumb tag removed. Both the supplied cartridge
and the exported manifest must match the inventory identity.

Use a matching ELF's typed symbols, verified script formats, callback tables or
source-derived callback inventories as evidence. Record provenance in `sources`
and the inventory's limits in `scope`. A symbol list containing data, unused code
or stripped instruction-mode information needs review before becoming a required
entry list. Required callbacks missing from the registry must be fixed or added
through verified analysis profiles before compilation. This gate checks static
entry coverage; execution, rendering and save tests remain necessary.

For Emerald BPEE revision 0, pret publishes a [symbol table](https://github.com/pret/pokeemerald/blob/symbols/pokeemerald.sym).
Its [CI](https://github.com/pret/pokeemerald/blob/master/.github/workflows/build.yml)
builds with comparison enabled before publishing symbols; the expected
[ROM SHA-1](https://github.com/pret/pokeemerald/blob/master/rom.sha1) must match the
owner's input. Battle scripts identify visual/sound task names; SpriteTemplate
callback fields provide tagged code pointers. Named callback families can add
review candidates. Absence of a direct ROM pointer is not a proof that a symbol
is unreachable, so keep uncertain cases visible instead of silently dropping them.
