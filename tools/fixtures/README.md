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

## Original Switch CPU fixture

`switch-cpu.S`, `.ld` and `.hex` are an original MIT AArch64 program and its build
inputs. The hex contains the linked `.text` bytes, with code at image offset
0x100 and data references at 0x2000. `tools/switch_fixture.py` packages it into
plain/compressed NSO or homebrew NRO without any SDK or game bytes. Tests compare
its statically generated C against independent Unicorn execution. See
[the Switch development guide](../../docs/future/switch.md).

`switch-module-main.S` and `switch-module-sdk.S` are a second original MIT
fixture. Their `.text`/`.rodata`/`.data` hex and `switch-module-symbols.json` come
from linking each assembly file separately with `switch-cpu.ld` and `_entry` as
the entry symbol. `tools/switch_exefs_fixture.py` adds independently constructed
MOD0 dynamic tables, import/export symbols, SysV or GNU hash tables, RELA/RELR,
constructors and NPDM stack metadata. No Nintendo SDK implementation is present
in the module named `sdk`. The fixtures prove cross-module calls and bounded
services; they do not qualify a retail game runtime.

`switch-exclusive.S` and `switch-exclusive.hex` are an original MIT AArch64
128-bit exclusive load/store test. The desktop qualification tool places this
code into the synthetic testkit NRO. LDXP/STXP and LDAXP/STLXP both return success
and update a pair from `(0x11, 0x22)` to `(0x13, 0x24)`. Regenerate the hex by
assembling for `aarch64-linux-gnu` and extracting the ELF `.text` section. No game
assets are used. `tools/switch_desktop_fixtures.rs` builds the other desktop
homebrew fixtures from the pinned, MIT-licensed Kirikae testkit.
