"""Original Heartbeat-format resources, known LZSS tokens and console access."""

import hashlib
import json
from pathlib import Path
import random
import struct

import pytest

from decompnet.cli import main
from decompnet.rom import psx_hbd, psx_lzss, psx_layout
from decompnet.rom.errors import RomError
from .test_overlays import _iso, _resident_exe


def archive(tag=0):
    raw, unpacked = b"original raw resource " * 140, b"original compressed resource " * 120
    encoded = psx_lzss.encode(unpacked)
    entries = [(raw, len(raw), 0, 31), (encoded, len(unpacked), 0x500, 14)]
    table = b"".join(struct.pack("<IIIHH", len(data), size, 0, flags, kind) for data, size, flags, kind in entries)
    payload = b"".join(data for data, _, _, _ in entries)
    count = (16 + len(table) + len(payload) + 2047) // 2048
    block = (struct.pack("<4I", len(entries), count, len(payload), tag) + table + payload).ljust(count * 2048, b"\0")
    return b"opaque volume sector".ljust(2048, b"\0") + block + b"opaque ending sector".ljust(2048, b"\0"), [raw, unpacked]


@pytest.mark.parametrize("wire,size,expected", [
    (b"\x07ABC", 3, b"ABC"),
    (b"\x07ABC\0\0\0\0", 3, b"ABC"),
    (b"\0\0\0", 3, bytes(3)),
    (b"\x03AB\xee\xf3\0\0\0", 7, b"ABABABA"),
], ids=["literals", "zero-terminator", "zero-ring", "overlapping-token"])
def test_lzss_wire_vectors_include_zero_ring_and_overlapping_final_token(wire, size, expected):
    assert psx_lzss.decode(wire, size) == expected


@pytest.mark.parametrize("data", [b"", bytes(10000), random.Random(7).randbytes(9000), bytes(range(256)) * 40],
                         ids=["empty", "zero-window", "random-window", "repeated-window"])
def test_lzss_window_wrap_literals_alignment_and_bounds(data):
    encoded = psx_lzss.encode(data)
    assert len(encoded) % 4 == 0
    assert psx_lzss.decode(encoded, len(data)) == data
    assert psx_layout.transform(encoded, {"codec": "hbd-lzss", "size": len(data)}) == data
    if data:
        with pytest.raises(RomError):
            psx_lzss.decode(encoded[:1], len(data))
    with pytest.raises(RomError, match="trailing"):
        psx_lzss.decode(encoded + b"extra", len(data))


@pytest.mark.parametrize("tag", [0, 1])
def test_hbd_repacking_preserves_disc_tag_unknown_sectors_and_other_members(tag):
    original, values = archive(tag)
    read = lambda at, size: original[at:at + size]
    catalog = psx_hbd.inventory(read, len(original))
    assert len(catalog["blocks"]) == 1 and catalog["opaque_sectors"] == 2
    block = catalog["blocks"][0]
    assert block["disc_tag"] == tag
    assert [psx_hbd.decoded(read, m) for m in block["members"]] == values
    unchanged, changes = psx_hbd.replace(read, len(original), 1, {1: values[1]})
    assert not changes and unchanged == original[2048:-2048]
    replacement = values[1].replace(b"original", b"modified")
    rebuilt, changes = psx_hbd.replace(read, len(original), 1, {1: replacement})
    modified = original[:2048] + rebuilt + original[-2048:]
    reread = lambda at, size: modified[at:at + size]
    result = psx_hbd.block(reread, len(modified), 1)
    assert result["disc_tag"] == tag and result["sectors"] == block["sectors"]
    assert psx_hbd.decoded(reread, result["members"][0]) == values[0]
    assert psx_hbd.decoded(reread, result["members"][1]) == replacement
    assert changes[0]["sha256"] == hashlib.sha256(replacement).hexdigest()
    with pytest.raises(RomError, match="growth"):
        psx_hbd.replace(read, len(original), 1, {1: random.Random(8).randbytes(20000)})


def test_hbd_respects_raw_alignment_allocation_hints_and_unknown_flags():
    original, _ = archive()
    data = bytearray(original)
    # An allocated raw member can be edited without inventing its uninitialized tail.
    old = struct.unpack_from("<I", data, 2048 + 16)[0]
    struct.pack_into("<I", data, 2048 + 20, old + 400)
    read = lambda at, size: bytes(data[at:at + size])
    item = psx_hbd.block(read, len(data), 1)
    value = psx_hbd.decoded(read, item["members"][0])
    assert len(value) == old
    rebuilt, _ = psx_hbd.replace(read, len(data), 1, {0: b"x" + value[1:]})
    assert struct.unpack_from("<I", rebuilt, 20)[0] == old + 400
    with pytest.raises(RomError, match="allocation"):
        psx_hbd.replace(read, len(data), 1, {0: value + b"x"})
    struct.pack_into("<H", data, 2048 + 28, 0x46)
    item = psx_hbd.block(read, len(data), 1)
    assert item["members"][0]["codec"] == "unknown"
    with pytest.raises(RomError, match="unknown"):
        psx_hbd.decoded(read, item["members"][0])


@pytest.mark.parametrize("height", [70, 32, 300])
def test_gpu_upload_headers_keep_packed_rectangle_and_only_accept_same_length_edits(height):
    x, y, width = 896, 0 if height != 32 else 208, 64 if height != 32 else 16
    packed = x | y << 10 | width << 20 | (height >> 8) << 30
    flags, data = height & 255, bytes((i * 7) % 256 for i in range(width * height * 2))
    header = struct.pack("<IIIHH", len(data), len(data), packed, flags, 1)
    sectors = (32 + len(data) + 2047) // 2048
    original = (struct.pack("<4I", 1, sectors, len(data), 1) + header + data).ljust(sectors * 2048, b"\0")
    read = lambda at, count: original[at:at + count]
    member = psx_hbd.block(read, len(original), 0)["members"][0]
    assert member["codec"] == "raw" and member["upload"] == {"x": x, "y": y, "width_words": width, "height": height}
    assert psx_hbd.decoded(read, member) == data
    replacement = bytes([data[0] ^ 1]) + data[1:]
    result, _ = psx_hbd.replace(read, len(original), 0, {0: replacement})
    assert result[:32] == original[:32] and result[32:32 + len(data)] == replacement
    with pytest.raises(RomError, match="rectangle"):
        psx_hbd.replace(read, len(original), 0, {0: data + b"1234"})
    for invalid in (packed ^ (1 << 20), packed | 1023, packed | (511 << 10)):
        assert psx_hbd.upload_rectangle(len(data), len(data), invalid, flags, 1) is None
    assert psx_hbd.upload_rectangle(len(data), len(data), packed, flags | 256, 1) is None
    assert psx_hbd.upload_rectangle(len(data), len(data) + 1, packed, flags, 1) is None


def test_console_archive_inventory_and_extraction_do_not_need_compilers(tmp_path, capsys):
    packed, values = archive(1)
    image = _iso({"SYSTEM.CNF": b"BOOT=cdrom:\\GAME.EXE;1\n", "GAME.EXE": _resident_exe(), "DATA.HBD": packed})
    rom = tmp_path / "original.iso"
    rom.write_bytes(image)
    args = ["psx", "archive", "inspect", str(rom), "--file", "DATA.HBD"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["block_count"] == 1 and report["member_count"] == 2 and "blocks" not in report
    output = tmp_path / "resource.bin"
    args = ["psx", "archive", "extract", str(rom), "--file", "DATA.HBD", "--sector", "1", "--member", "1", "--output", str(output)]
    assert main(args) == 0
    assert output.read_bytes() == values[1]
    assert rom.read_bytes() == image
    assert main(args[:-1] + [str(rom)]) == 1
    assert rom.read_bytes() == image
