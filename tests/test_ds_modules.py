"""Original module-layout and BLZ vectors; no retail, SDK, BIOS or firmware payloads."""

import struct

import pytest

from decompnet.forks.scratch_dsd import crc16
from decompnet.rom.dsprot import SIGNATURES, detect
from decompnet.rom.nds_modules import NdsImage, decompress_blz


def blz_vector():
    # Reverse decoder: eight literals, then seven 8-byte copies at distance 8.
    stream = bytes(reversed(b"\0HGFEDCBA" + b"\xfe" + b"\x50\x05" * 7))
    stored = b"PREF" + stream + (len(stream) + 8).to_bytes(3, "little") + b"\x08" + struct.pack("<I", 32)
    return stored, b"PREF" + b"ABCDEFGH" * 8


def fixture():
    data = bytearray(0x6000)
    data[:12], data[12:16] = b"ORIGINALTEST", b"ADQE"
    struct.pack_into("<4I", data, 0x20, 0x4000, 0x02000004, 0x02000000, 0x100)
    struct.pack_into("<4I", data, 0x30, 0x5000, 0x02380000, 0x02380000, 0x100)
    struct.pack_into("<2I", data, 0x48, 0x380, 24)
    struct.pack_into("<2I", data, 0x50, 0x300, 64)
    struct.pack_into("<2I", data, 0x58, 0x340, 32)
    compressed, expanded = blz_vector()
    for at, oid, fid, address, code, flags in (
        (0x300, 41, 0, 0x02200000, 16, 0),
        (0x320, 3, 1, 0x02200000, len(expanded), 0x3000000 | len(compressed)),
        (0x340, 41, 2, 0x02300000, 16, 0),
    ):
        struct.pack_into("<8I", data, at, oid, address, code, 13, address, address + 4, fid, flags)
        lo, stored = 0x5100 + fid * 0x100, compressed if fid == 1 else bytes(range(16))
        data[lo:lo + len(stored)] = stored
        struct.pack_into("<2I", data, 0x380 + fid * 8, lo, lo + len(stored))
    # ARM7 functions with independently specified ARMv4T instructions.
    data[0x5000:0x5008] = bytes.fromhex("0700a0e31eff2fe1")  # mov r0,#7; bx lr
    data[0x5010:0x5014] = bytes.fromhex("07207047")  # movs r0,#7; bx lr
    seal(data)
    return data


def seal(data):
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))


def test_unordered_ids_overlapping_runtime_addresses_and_both_cpus():
    image = NdsImage(bytes(fixture()))
    assert set(image.modules) == {"arm9", "arm7", "arm9:ov41", "arm9:ov3", "arm7:ov41"}
    assert image.modules["arm9:ov41"].address == image.modules["arm9:ov3"].address
    assert image.modules["arm9:ov41"].bss_size == 13
    assert image.code("arm9:ov3") == blz_vector()[1]
    info = image.inspect()
    assert not info["secure_area_validated"] and not info["bios_required_for_inspection"]
    overlay = next(m for m in info["modules"] if m["name"] == "arm9:ov3")
    assert overlay["signed"] and overlay["decoded"] and not overlay["authentication_verified"]


def test_opaque_secure_area_does_not_block_arm7(monkeypatch):
    monkeypatch.delenv("DECOMP_ARM7_BIOS", raising=False)
    data = fixture()
    data[0x4000:0x4008] = b"OPAQUE!!"
    image = NdsImage(bytes(data))
    assert image.code("arm7")[:8] == bytes.fromhex("0700a0e31eff2fe1")
    with pytest.raises(ValueError, match="secure-area"):
        image.code("arm9")


def autoload_fixture():
    data = fixture() + bytes(0x1000)
    base, offset = 0x02380000, 0x6000
    struct.pack_into("<4I", data, 0x30, offset, base, base, 0x500)
    struct.pack_into("<I", data, offset, 0xE59F0018)  # ldr r0,[pc,#0x18]
    struct.pack_into("<I", data, offset + 0x20, base + 0x80)
    struct.pack_into("<5I", data, offset + 0x80, base + 0x4E8, base + 0x500, base + 0x100,
                     base + 0x100, base + 0x100)
    struct.pack_into("<6I", data, offset + 0x4E8, 0x037F8000, 0x100, 16, 0x027E0000, 0x2E8, 24)
    data[offset + 0x100:offset + 0x104] = b"AUTO"
    data[offset + 0x200:offset + 0x204] = b"LOAD"
    seal(data)
    return data


def test_arm7_copied_code_uses_runtime_destinations_and_excludes_descriptor_bytes():
    image = NdsImage(bytes(autoload_fixture()))
    assert len(image.code("arm7")) == 0x100 and image.arm7_program_size == 0x500
    assert image.code("arm7:autoload0")[:4] == b"AUTO"
    assert image.code("arm7:autoload1")[:4] == b"LOAD"
    assert image.modules["arm7:autoload0"].address == 0x037F8000
    assert image.modules["arm7:autoload1"].address == 0x027E0000
    assert image.modules["arm7:autoload0"].bss_size == 16
    assert image.modules["arm7:autoload1"].bss_size == 24


def test_unreferenced_or_invalid_arm7_parameters_do_not_invent_runtime_addresses():
    data = autoload_fixture()
    data[0x6000:0x6004] = bytes(4)  # remove the loader's reference
    assert not any("autoload" in name for name in NdsImage(bytes(data)).modules)
    data = autoload_fixture()
    struct.pack_into("<I", data, 0x64E8, 0xFFFFFFF0)  # outside DS memory
    assert not any("autoload" in name for name in NdsImage(bytes(data)).modules)


@pytest.mark.parametrize("offset,fmt,value,reason", [
    (0x12, "B", 2, "TWL"),
    (0x30, "I", 0xFFFF, "outside ROM"),
    (0x34, "I", 0x03800000, "entrypoint"),
    (0x38, "I", 0xFFFFFFF0, "32-bit"),
    (0x4C, "I", 23, "multiple of 8"),
    (0x54, "I", 63, "multiple of 32"),
    (0x320, "I", 41, "duplicate"),
    (0x318, "I", 99, "file ID"),
    (0x384, "I", 0x50FF, "outside ROM"),
    (0x314, "I", 0x03000000, "constructors"),
])
def test_bad_module_layouts(offset, fmt, value, reason):
    data = fixture()
    struct.pack_into("<" + fmt, data, offset, value)
    seal(data)
    with pytest.raises(ValueError, match=reason):
        NdsImage(bytes(data))


def test_bad_header_crc():
    data = fixture()
    data[0] ^= 1
    with pytest.raises(ValueError, match="header CRC"):
        NdsImage(bytes(data))


@pytest.mark.parametrize("flag,reason", [(0x4000000, "unknown overlay"), (0x3000020, "FAT extent")])
def test_unsupported_flags_or_compressed_extents_remain_inspection_errors(flag, reason):
    data = fixture()
    struct.pack_into("<I", data, 0x33C, flag)
    image = NdsImage(bytes(data))
    module = next(m for m in image.inspect()["modules"] if m["name"] == "arm9:ov3")
    assert not module["decoded"] and reason in module["reason"]


@pytest.mark.parametrize("mutation", ["short", "footer", "expanded", "distance", "excess", "truncated"])
def test_malformed_blz(mutation):
    stored, expected = blz_vector()
    data = bytearray(stored)
    if mutation == "short":
        data = data[:7]
    elif mutation == "footer":
        data[-5] = 255
    elif mutation == "expanded":
        data[-1] = 255
    elif mutation == "distance":
        data[4:6] = b"\xff\x5f"
    elif mutation == "excess":
        data[-4:] = struct.pack("<I", 31)
    else:
        data[-8:-5] = (9).to_bytes(3, "little")
    with pytest.raises(ValueError):
        decompress_blz(bytes(data), len(expected))


@pytest.mark.parametrize("version", SIGNATURES)
def test_ds_protect_signatures_in_decoded_modules(version):
    signature = SIGNATURES[version]
    assert detect(b"\0" * 4 + signature + signature, 0x02300000) == [
        {"version": version, "offset": 4, "address": 0x02300004},
        {"version": version, "offset": 28, "address": 0x0230001C}]
    assert not detect(b"x" + signature)
    assert not detect(signature[:-1])
