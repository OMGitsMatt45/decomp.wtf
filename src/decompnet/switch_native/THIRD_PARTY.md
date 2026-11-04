# Switch source origins

All four upstream source snapshots are pinned by commit and archive SHA-256 in
`sources.json`. The source-pull helper downloads their complete trees into a
separate development workspace and preserves each tree's notices. These projects
use different ABIs; components require explicit adapters.

- **nxport**, `nxporting/nxport`, MIT: the vendored `crates/lifter` is unchanged.
  It emits C functions, function tables and the source CPU dispatcher. Its own
  `LICENSE` and `LICENSE-LASRecomp` are retained. decomp.wtf adds a Rust file
  adapter and code-integrity checks to the generated output.
- **LASRecomp**, `peiikai/LASRecomp`, MIT for its own code: nxport's lifter and
  SIMD/CPU helpers are ports of this project. The original copyright remains in
  the source and license. Its full runtime is available in the pinned development
  tree; the game-specific runtime has not been integrated.
- **Kirikae**, `Cor3Duo/kirikae`, MIT OR Apache-2.0: `media.py` ports the NSO/NRO
  layouts and raw LZ4 loader under the MIT option, with additional validation and
  input hashing. `exefs.py` follows its load order and MOD0/dynamic layouts;
  local changes add strict RELA/RELR linking, visibility/weak-symbol resolution,
  source-set identity and constructor validation. The register and HIPC/CMIF
  layouts in `kernel.c` follow its MIT `horizon.rs`, `ipc.rs` and `services/sm.rs`,
  adapted to the nxport C callback ABI with strict unsupported-call reporting.
  The MIT and Apache notices are retained. `vendor/kirikae-src` preserves the
  unmodified a64, loader, maxwell, rt and testkit crates; the exact source inventory
  is pinned in `desktop/runtime-sources.json`. Desktop exports apply checked
  patches from `desktop/patches.py` and include this editable runtime, its shader
  translator, Vulkan graphics, audio, input and save services. The normal desktop
  build excludes the guest CPU interpreter and refuses a combined native plus
  diagnostic-interpreter feature build. The Cranelift object generator is excluded.
- **nxrecomp**, `drakolordx7/nxrecomp`, GPL-3.0-or-later: the pinned development
  checkout supplies an external comparison/oracle and runtime candidate. No
  nxrecomp implementation is embedded in the MIT adapter or generated CPU output.
  Any later incorporation must retain its notices and applicable GPL terms.

Repository URLs are `https://github.com/` followed by the owner/project above.
These development outputs include neither game data from upstream nor any
retail compatibility claim. Owner-supplied module bytes stay in the private
export. Generated C preserves register/memory semantics; it does not recover the
game's original source-level types or names.
