# Original 3DS fixtures

These ARM11 programs and generated fixture data are CC0 and contain no console
SDK, game or firmware bytes. `ctr-services.S` is the source for its matching hex.
`ctr-save.S` and its matching hex are an original relocatable save counter:
first-use formatting is allowed only for the exact not-formatted result, and
later launches read/increment the persisted file without clearing other data.

`ctr-arm-code.blz.hex` encodes the original `arm` fixture's full executable/data
image. It was generated independently with ndspy 4.2.0's `codeCompression.compress`
and round-tripped through that decoder. The compressor is used only to generate
this original data; no ndspy source or runtime dependency is shipped. Tests also
compare the complete decoded image against the pinned MIT 3dsrecomp decoder and
execute the generated native C against Unicorn. This prevents a locally written
encoder and decoder from agreeing on the same displacement mistake.
