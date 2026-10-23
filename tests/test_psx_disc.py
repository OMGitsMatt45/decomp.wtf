"""Original multi-overlay PS1 discs: exact file extents and preserved sector envelopes."""

import copy
import io
import struct

import pytest

from decompnet.rom import chd, detect, psx, psx_disc
from decompnet.rom.n64 import RomError
from .test_overlays import _iso, _overlay, _resident_exe


def fixture(sector_size=2048, skip=0):
    overlay_exe = bytearray(_resident_exe())
    struct.pack_into("<IIII", overlay_exe, 0x10, 0x80180000, 0, 0x80180000, 0x800)
    overlay_exe[0x800:] = _overlay(0x80180000, 40).ljust(0x800, b"\0")
    image = _iso({"SYSTEM.CNF": b"BOOT = cdrom:\\DEMOQ_PS1.EXE;1\r\n",
                  "DEMOQ_PS1.EXE": _resident_exe() + b"preserve executable file trailer",
                  "BATTLE.BIN": b"original overlay header".ljust(64, b"\0") + _overlay(0x80180040, 40),
                  "FIELD.EXE": bytes(overlay_exe), "MUSIC.VAB": bytes(range(256)) * 32})
    if sector_size == 2048:
        return image
    raw = bytearray()
    for lba in range(len(image) // 2048):
        sector = bytearray((i * 17 + lba * 7) % 256 for i in range(sector_size))
        sector[:12] = b"\0" + b"\xff" * 10 + b"\0"
        sector[15] = 1 if skip == 16 else 2
        if skip == 24:
            sector[16:24] = bytes([0, 0, 8, 0]) * 2
        sector[skip:skip + 2048] = image[lba * 2048:(lba + 1) * 2048]
        raw += sector
    # Opaque audio after the filesystem must survive too.
    raw += bytes((i * 13) % 256 for i in range(sector_size * 3))
    return bytes(raw)


def joined(picked):
    data = bytearray(picked.data)
    segs = []
    for name, code, load, _ in picked.overlays:
        data += bytes(-len(data) % 16 + 16)
        segs.append({"name": "ovl_" + name, "rom_start": len(data), "vram": load})
        data += code
    if picked.overlays:
        data += bytes(-len(data) % 16)
    return bytes(data), segs


@pytest.mark.parametrize("sector_size,skip", [(2048, 0), (2352, 16), (2352, 24), (2448, 16), (2448, 24)])
def test_full_disc_roundtrip_preserves_headers_trailers_audio_subcode(tmp_path, sector_size, skip):
    original = fixture(sector_size, skip)
    picked = detect.identify(original)
    assert picked.disc["supported"], picked.disc
    assert len(picked.overlays) == 2
    assert {o[2] + o[3] for o in picked.overlays} == {0x80180040, 0x80180000}
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    path, output = tmp_path / "original disc.bin", tmp_path / "build/disc.bin"
    path.write_bytes(original)
    assert psx_disc.analysis(path, layout) == image
    psx_disc.rebuild(path, image, layout, output)
    assert output.read_bytes() == original
    changed = bytearray(image)
    changed[-8] ^= 1
    with pytest.raises(RomError, match="source-built PS1 analysis image differs"):
        psx_disc.rebuild(path, bytes(changed), layout, output)
    assert not output.exists() and not output.with_name(output.name + ".tmp").exists()


def test_wrong_disc_extent_target_and_load_are_rejected(tmp_path):
    original = fixture()
    picked = detect.identify(original)
    image, segments = joined(picked)
    layout = psx_disc.bind(picked.disc, segments, image)
    path = tmp_path / "original.iso"
    path.write_bytes(original)
    for field, value in [("lba", 18), ("file_size", 7), ("analysis_offset", len(image))]:
        bad = copy.deepcopy(layout)
        bad["maps"][1][field] = value
        with pytest.raises(RomError):
            psx_disc.analysis(path, bad)
    bad = copy.deepcopy(layout)
    bad["maps"][1]["sha256"] = "0" * 64
    with pytest.raises(RomError, match="program SHA-256"):
        psx_disc.analysis(path, bad)
    bad_segments = copy.deepcopy(segments)
    bad_segments[0]["vram"] += 4
    with pytest.raises(RomError, match="load address"):
        psx_disc.bind(picked.disc, bad_segments, image)
    changed = bytearray(original)
    changed[-1] ^= 1
    path.write_bytes(changed)
    with pytest.raises(RomError, match="original PS1 disc differs"):
        psx_disc.analysis(path, layout)


def test_truncated_raw_disc_fails_without_looping():
    disc = psx._Disc(fixture(2352, 24)[:19 * 2352])
    with pytest.raises(RomError, match="truncated"):
        disc.read(500, 20)


@pytest.mark.parametrize("size,skip", [(2048, 0), (2352, 24)])
def test_huge_corrupt_file_extents_fail_before_reading_or_allocating(size, skip):
    class BoundedReads(io.BytesIO):
        def read(self, count=-1):
            assert 0 <= count <= 1 << 20, "corrupt metadata requested an unbounded read"
            return super().read(count)

    disc = psx._Disc(BoundedReads(fixture(size, skip)))
    with pytest.raises(RomError, match="file extent exceeds"):
        disc.read(19, 0xFFFFFFFF)


@pytest.mark.parametrize("kind", ["short", "endian", "cycle", "interleave", "multi_extent", "duplicate"])
def test_bad_iso_directories_fail_or_report_program_only(kind):
    image = bytearray(fixture())
    at = 18 * 2048 + 68  # first ordinary directory record
    if kind == "short":
        image[at] = 12
    elif kind == "endian":
        image[at + 6] ^= 1
    elif kind == "cycle":
        image[at + 25] = 2
        image[at + 2:at + 10] = struct.pack("<I", 18) + struct.pack(">I", 18)
        image[at + 10:at + 18] = struct.pack("<I", 2048) + struct.pack(">I", 2048)
    elif kind in ("interleave", "multi_extent"):
        # Keep the boot program readable: make an unrelated file unsupported.
        while image[at + 33:at + 38] != b"MUSIC":
            at += image[at]
        image[at + (26 if kind == "interleave" else 25)] = 1 if kind == "interleave" else 0x80
    else:
        length = image[at]
        end = at
        while image[end]:
            end += image[end]
        image[end:end + length] = image[at:at + length]
    try:
        picked = detect.identify(bytes(image))
    except RomError:
        assert kind in ("short", "endian", "cycle")
    else:
        assert not picked.disc["supported"]
        assert picked.disc["reason"]


def test_partial_sector_and_form2_code_report_program_only():
    picked = detect.identify(fixture() + b"x")
    assert not picked.disc["supported"] and "partial sector" in picked.disc["reason"]
    raw = bytearray(fixture(2352, 24))
    disc = psx._Disc(raw)
    _, lba, _, _ = next(e for e in disc.entries(18, 2048) if e[0] == "BATTLE.BIN")
    raw[lba * 2352 + 18] |= 0x20
    raw[lba * 2352 + 22] |= 0x20
    picked = detect.identify(bytes(raw))
    assert not picked.disc["supported"] and "Form 1" in picked.disc["reason"]


def test_small_psx_headers_and_payloads_outside_ram_fail_cleanly():
    with pytest.raises(RomError, match="truncated"):
        psx.read_exe(b"PS-X EXE")
    image = bytearray(_resident_exe())
    struct.pack_into("<I", image, 0x18, 0x801FFFF0)
    with pytest.raises(RomError, match="load address or size"):
        psx.read_exe(bytes(image))


def test_nested_boot_path_does_not_hide_an_overlay_with_the_same_basename():
    image = bytearray(_iso({"SYSTEM.CNF": b"BOOT = cdrom:\\BOOT\\MAIN.EXE;1\n",
                            "BOOT": bytes(2048), "MAIN.EXE": _resident_exe()}))
    at = 18 * 2048 + 68
    records = {}
    while image[at]:
        n = image[at]
        name = bytes(image[at + 33:at + 33 + image[at + 32]]).split(b";")[0].decode()
        records[name] = at
        at += n
    # Turn BOOT into a directory and put its own MAIN.EXE in it.
    image[records["BOOT"] + 25] = 2
    boot_lba = int.from_bytes(image[records["BOOT"] + 2:records["BOOT"] + 6], "little")
    record = bytearray(image[records["MAIN.EXE"]:records["MAIN.EXE"] + image[records["MAIN.EXE"]]])
    lba = len(image) // 2048
    record[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    image[boot_lba * 2048:boot_lba * 2048 + len(record)] = record
    image += _resident_exe()
    picked = detect.identify(bytes(image))
    assert picked.disc["supported"], picked.disc
    assert picked.disc["maps"][0]["path"] == "BOOT/MAIN.EXE"
    assert any(m["path"] == "MAIN.EXE" and m["segment"] != "main" for m in picked.disc["maps"])


def test_small_chd_paths_use_the_decoder_and_report_program_only(tmp_path, monkeypatch):
    class OriginalDecodedFrames(io.BytesIO):
        def __init__(self, path):
            super().__init__(fixture(2448, 24))

    path = tmp_path / "small disc.chd"
    path.write_bytes(chd.MAGIC + bytes(100))
    monkeypatch.setattr(chd, "Chd", OriginalDecodedFrames)
    picked = detect.identify(path)
    assert picked.platform == "psx" and len(picked.overlays) == 2
    assert not picked.disc["supported"] and "CHD" in picked.disc["reason"]
