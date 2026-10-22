# DSi container foundation

DSi can reuse ARM instruction analysis and period compilers, but TWL containers
add ARM9i/ARM7i programs, Modcrypt ranges and authentication data. The pinned
ds-decomp ROM builder does not preserve those fields. DSi images remain rejected
by the ordinary DS importer.

This first implementation validates the header CRC and stored program/digest/
Modcrypt bounds. It can copy their exact stored bytes and the full header into
a new private directory, including opaque HMAC and RSA metadata. ARM9i/ARM7i
reserved descriptor words are not treated as entrypoints. No authentication or
decryption success is claimed.

```sh
uv run python tools/dsi_inspect.py /path/to/your/title.nds
uv run python tools/dsi_inspect.py /path/to/your/title.nds --output-dir /private/path/title-stored
uv run pytest -q tests/test_dsi.py
```

The output directory must be outside this checkout. It contains private ROM
bytes, possibly still encrypted. No BIOS or firmware download is required for
inspection; do not commit console files or extracted programs.

Further work: verified Modcrypt/key handling, TWL-aware ARM9i/ARM7i analysis,
digest/HMAC/signature preservation and validation, strict whole-image rebuilds,
and emulator qualification with owner-supplied inputs. No DSi game has been
qualified by these original-container tests.
