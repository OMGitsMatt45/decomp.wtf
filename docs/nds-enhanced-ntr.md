# Enhanced cartridges in the native NTR backend

The experimental native exporter accepts unit-code 2 cartridges in ordinary
DS (NTR) mode. It retains the complete owner-supplied asset and records
`execution_mode: ntr` and `dsi_enhanced: true` in its manifests. This does not
enable DSi-exclusive unit-code 3 cartridges, enhanced hardware, cameras,
ARM9i/ARM7i execution, or network services. The matching-ROM importer and the
default module inspector keep their existing TWL rejection.

The pinned decoder requires an NTR-shaped ARM9 footer, three-word autoload
descriptors, conventional startup roots, and two TCM configuration files.
SDK-5 enhanced inputs instead carry referenced four-word descriptors, arbitrary
autoload regions, and a distinct constructor/startup layout. Analysis therefore
uses a temporary decoder container with canonical descriptors, a synthetic
startup wrapper, and any required TCM placeholders. The wrapper identifies both
the original entry and its declared main tail target. Region indexes are
normalized only in that temporary view.

After decoding, the exporter removes the synthetic startup and TCM modules,
restores every changed parameter word, and retains all actual initialized
autoload images under their original addresses and identities. Neither the
analysis header nor its synthetic code enters runtime assets or dispatch.
ARM7 analysis validates the four-word form independently, keeping initializer
addresses separate from BSS sizes. Malformed, overlapping, unreferenced or
ambiguous layouts fail closed.

This path currently requires a decrypted secure area (explicitly selected, or
recognized by its normal decrypted marker), an aligned ARM startup and static
split, and validated SDK-5 autoload metadata. It is not a general DSi importer.
Original regression inputs cover header routing, layout validation, restoration,
arbitrary-region preservation, startup roots, generated native hardware
execution and persistent cartridge saves. Retail compatibility still requires
per-input callback review and actual gameplay qualification.

ARM7 functions inferred only from unreferenced prologue patterns remain unknown
bytes until a real entry, call or pointer supplies evidence. This avoids
promoting constant data or unused foreign-mode payloads into callable code.
Deferred candidates retain their original extent and decoded-image checksum.
A real call or pointer may later qualify them; the normal graph validator
then checks that full extent across same-state imported frame fragments.
Unreferenced candidates and mismatched image bounds remain deferred.
Guarded ARM halfword-offset switches keep their tables as data and dispatch
using the actual loaded offset. Flag-preserving setup between the comparison
and its unsigned guard is accepted only while the compared key stays intact.

Bounded original ARM word-copy loops and two-word stack trampolines can produce
additional static modules at their runtime destinations. Literal source bytes,
copy bounds, following branch, position-independent control flow and constant
stack bases are checked; original startup performs every copy unchanged.
Reserved module IDs at or below -1024 identify these mutable code variants.
The existing live-memory hash resolver selects successive bodies and also
checks a copy with only one candidate, rejecting unknown modifications.

The NTR runtime exposes absent TWL configuration IO at 04004000h..04004FFFh as
zero with ignored writes. Returning all ones falsely sets SCFG_EXT7 bit31 and
routes enhanced startup into unavailable hardware. See [GBATEK SCFG](https://problemkaputt.de/gbatek.htm#dsicontrolregistersscfg)
and the independent [NDS-mode IO reference](https://github.com/melonDS-emu/melonDS/blob/master/src/NDS.cpp).

Direct NTR boot copies only the documented 170h-byte header into shared boot
RAM. Copying the extended header through 1FFh overwrites SDK lock words with
enhanced-cartridge metadata, leaving one CPU waiting for the other. The full
original header remains available from the cartridge. [GBATEK boot RAM](https://problemkaputt.de/gbatek.htm#biosramusage)
documents the header and following zero-filled memory separately.

Frameless functions that preserve their incoming LR in another register retain
normal return semantics. The return register must be copied unconditionally at
entry and remain untouched, including by every directly called leaf. Unknown
callees, indirect calls, conditional saves and stack frames reject that proof.

IR cartridge codes beginning with I accept the documented 00h savedata prefix
before their flash commands. Native flash status, write-enable, erase and raw
save persistence remain in the existing chip implementation. The runtime models
the newer IR firmware's `08h,ver` identification query with version `AAh`.
Identification ends at chip-select release, preserves flash write-enable, and
does not reinterpret commands inside the `00h` savedata framing. Plain cartridges
retain their existing command behavior. Infrared packet transport is not
implemented. [GBATEK IR SPI](https://problemkaputt.de/gbatek.htm#dscartinfraredcartridgespicommands)
documents both firmware versions, the framing and code marker.
