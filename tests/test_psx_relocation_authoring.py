"""Explicit additive loader relocations can be inverted and authored safely."""

import copy
import hashlib
import struct
import zlib

import pytest

from decompnet.rom import detect, psx_layout
from decompnet.rom.errors import RomError
from decompnet.rom.psx import _Disc
from .test_overlays import _iso, _resident_exe


@pytest.mark.parametrize("kind", ["R_MIPS_32", "R_MIPS_26"])
@pytest.mark.parametrize("codec", ["raw", "zlib", "hbd-lzss"])
def test_reviewed_loader_base_can_author_changed_pointer_or_jump_and_decode_it_back(kind, codec):
    from decompnet.rom.psx_lzss import encode
    base = 0x80180000
    old_word = 4 if kind == "R_MIPS_32" else 0x0C000001
    body = old_word.to_bytes(4, "little") + bytes(60)
    stored = body if codec == "raw" else zlib.compress(body) if codec == "zlib" else encode(body)
    capacity = 128
    archive = stored.ljust(capacity, b"\0") + len(stored).to_bytes(4, "little")
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "CODE.ARC": archive})
    review = {"format": 1, "sha256": hashlib.sha256(image).hexdigest(), "modules": [{
        "name": "module", "path": "CODE.ARC", "offset": 0, "stored_size": len(stored), "size": len(body), "codec": codec,
        "load": base, "relocations": [{"offset": 0, "type": kind, "value": base + 4, "base": base}],
        "storage": {"capacity": capacity, "length_offset": capacity, "length_width": 4, "endian": "little"}}]}
    picked = detect.identify(image)
    psx_layout.apply(picked, image, review)
    mapping = picked.disc["maps"][1]
    old = psx_layout.transform(stored, mapping)
    changed = bytearray(old)
    new_word = base + 28 if kind == "R_MIPS_32" else 0x08000000 | ((base + 28) >> 2 & 0x3FFFFFF)
    changed[:4] = new_word.to_bytes(4, "little")
    encoded, storage = psx_layout.encode_mod(_Disc(image), mapping, changed, old)
    assert len(encoded) <= storage["capacity"]
    assert psx_layout.transform(encoded, mapping) == changed
    unrelocated = psx_layout.transform(encoded, dict(mapping, relocations=[]))
    assert int.from_bytes(unrelocated[:4], "little") == (28 if kind == "R_MIPS_32" else 0x08000007)
    wrong = copy.deepcopy(review)
    wrong["modules"][0]["relocations"][0]["base"] += 4
    with pytest.raises(RomError, match="encoded addend"):
        psx_layout.apply(detect.identify(image), image, wrong)
