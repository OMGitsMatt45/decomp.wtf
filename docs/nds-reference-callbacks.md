# Reviewed DS callback boundaries

An importer can identify a callback's epilogue as a separate function while omitting the enclosing callback entry. A scanner bounded by that fragment then stops before the callback can restore its own stack frame. Another imported extent can include a separate callback after its return.

Analysis integrations with a reviewed symbol resource can pass full boundaries to `decompnet.nds_native.callbacks.recover` through its optional `reference_entries` argument. Each record contains:

- `module_id`: the exact resident or overlay module ID.
- `address`: the aligned, even instruction address.
- `size`: the complete bounded extent, including any literal pool.
- `thumb`: a Boolean identifying the instruction mode.
- `module_sha256`: the SHA-256 of the initialized, decoded module image used by the manifest.

Bind the reference resource to the original input identity in the importing workflow. Record its source revision and content hash. A reference for one region, revision or overlay must not be treated as an address-only hint for another.

The recovery helper verifies module identity, bounds, alignment, mode and image hashes before adding entries. It rejects duplicate and overlapping reference extents. It then uses the normal instruction decoder to check the complete reachable graph, initialized executable bytes and literal conflicts. A root inside existing reachable instructions is rejected: a shared epilogue may require its caller's stack frame and is not an independent callable entry.

Accepted reference bounds can span partial importer records. Speculative roots inside those bounds do not partition the enclosing callback. Only validated instructions become code; literal pools remain data. Recovery evidence records the reference size and decoded-module hash, alongside ordinary pointer and call evidence.

The original regression fixture uses invented ARM/Thumb instructions. It covers a split epilogue, a callback folded into a broad extent, equal virtual addresses in separate overlays, mismatched hashes, invalid modes/bounds, shared instruction interiors and unsupported code. The compiled fixture checks return values, preserved registers and an unchanged guest stack pointer. These checks do not qualify an arbitrary external symbol map or establish retail gameplay compatibility.
