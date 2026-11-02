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
