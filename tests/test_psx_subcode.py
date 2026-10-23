"""Original Q packets, independent bitwise CRC, and actual CHD audio growth."""

import json
from pathlib import Path
import shutil

import pytest

from decompnet.rom import detect, psx_assets, psx_disc, psx_media, psx_subcode
from decompnet.rom.chd import Chd
from decompnet.rom.chd_write import rewrite
from decompnet.rom.n64 import RomError
from .test_psx_disc import joined


def check_bytes(data):
    # Polynomial division, independent of the production binascii implementation.
    value = int.from_bytes(data, "big") << 16
    for bit in range(len(data) * 8 + 15, 15, -1):
        if value & (1 << bit):
            value ^= 0x11021 << (bit - 16)
    return (value ^ 65535).to_bytes(2, "big")


def clock(frames):
    minute, rest = divmod(frames, 4500)
    second, frame = divmod(rest, 75)
    return bytes((n // 10) * 16 + n % 10 for n in (minute, second, frame))


def packet(absolute, relative=0, *, number=2, index=1, adr=1):
    if adr == 1:
        q = bytes([1, number // 10 * 16 + number % 10, index]) + clock(relative) + b"\0" + clock(absolute)
    elif adr == 2:
        q = bytes.fromhex("02123456789012300000")
        q = q[:9] + clock(absolute)[2:]
    else:
        chars = "USABC"
        codes = 0
        for char in chars:
            codes = codes << 6 | (ord(char) - 48)
        q = bytes([3]) + (codes << 2).to_bytes(4, "big") + bytes.fromhex("24123450") + clock(absolute)[2:]
    return q + check_bytes(q)


def interleaved(q):
    bits = f"{int.from_bytes(q, 'big'):096b}"
    return bytes((((i * 37) ^ 0xA5) & 0xBF) | int(bit) << 6 for i, bit in enumerate(bits))


def separated(raw):
    return int("".join(str((byte >> 6) & 1) for byte in raw), 2).to_bytes(12, "big")


@pytest.mark.parametrize("adr", [1, 2, 3])
def test_standard_q_retiming_preserves_all_other_subchannels_and_payloads(adr):
    q = packet(4490, 7, adr=adr)
    assert psx_subcode.crc(q[:10]) == q[10:]
    raw = interleaved(q)
    result = psx_subcode.retime(raw, 17, number=2, absolute=4490, relative=7)
    rewritten = separated(result)
    assert bytes(b & 0xBF for b in result) == bytes(b & 0xBF for b in raw)
    assert rewritten[10:] == check_bytes(rewritten[:10])
    if adr == 1:
        assert rewritten[:7] == q[:7] and rewritten[7:10] == clock(4507)
    else:
        assert rewritten[:9] == q[:9] and rewritten[9] == clock(4507)[2]


@pytest.mark.parametrize("damage", ["crc", "bcd", "data-control", "track", "index", "relative", "absolute", "reserved", "adr", "catalogue", "isrc"])
def test_nonstandard_or_protected_q_is_refused_without_repair(damage):
    q = bytearray(packet(330))
    if damage == "bcd":
        q[8] = 0x6A
    elif damage == "data-control":
        q[0] |= 0x40
    elif damage == "track":
        q[1] = 3
    elif damage == "index":
        q[2] = 0
    elif damage == "relative":
        q[5] = 1
    elif damage == "absolute":
        q[9] += 1
    elif damage == "reserved":
        q[6] = 1
    elif damage == "adr":
        q[0] = 5
    elif damage in ("catalogue", "isrc"):
        q = bytearray(packet(330, adr=2 if damage == "catalogue" else 3))
        q[8] |= 1  # reserved low nibble
    q[10:] = check_bytes(q[:10])
    if damage == "crc":
        q[11] ^= 1
    raw = interleaved(q)
    with pytest.raises(RomError, match="subcode"):
        psx_subcode.retime(raw, 7, number=2, absolute=330, relative=0)
    assert separated(raw) == q


def test_subcode_absence_countdown_and_time_overflow():
    assert psx_subcode.retime(bytes(96), 5, number=2, absolute=330, relative=0) == bytes(96)
    missing_q = bytes((i * 13) & 0xBF for i in range(96))
    assert psx_subcode.retime(missing_q, 5, number=2, absolute=330, relative=0) == missing_q
    for relative in (3, 2):
        q = packet(180, relative, index=0)
        result = psx_subcode.retime(interleaved(q), 7, number=2, absolute=180, relative=3, pregap=True)
        assert separated(result)[3:6] == clock(relative)
    with pytest.raises(RomError, match="time range"):
        psx_subcode.retime(interleaved(packet(449999)), 1, number=2, absolute=449999, relative=0)


def prepared_source(tmp_path, gap):
    """Use original MAME fixture PCM, replacing only metadata and Q packets."""
    source = Path(__file__).parent / "fixtures/psx-chd/cdfl.chd"
    prepared = tmp_path / "prepared.chd"
    with Chd(source) as image:
        image.seek(0)
        data = bytearray(image.read())
        metadata = list(image.metadata)
    tag, flags, text = metadata[1]
    if gap == "stored":
        text = text.replace(b"PREGAP:150 PGTYPE:AUDIO", b"PREGAP:3 PGTYPE:VAUDIO")
    elif gap == "postgap":
        first = metadata[0]
        metadata[0] = first[0], first[1], first[2].replace(b"POSTGAP:0", b"POSTGAP:5")
    metadata[1] = tag, flags, text
    absolute_start = 180 if gap == "stored" else 335 if gap == "postgap" else 330
    for frame in range(33):
        in_gap = gap == "stored" and frame < 3
        relative = 3 - frame if in_gap else frame - (3 if gap == "stored" else 0)
        adr = 2 if frame == 10 else 3 if frame == 20 else 1
        q = packet(absolute_start + frame, relative, index=0 if in_gap else 1, adr=adr)
        at = (32 + frame) * 2448 + 2352
        data[at:at + 96] = interleaved(q)
    def image(_):
        return len(data), metadata, lambda at, count: bytes(data[at:at + count])
    rewrite(source, prepared, {}, image=image)
    return prepared


@pytest.mark.parametrize("gap", ["virtual", "stored", "postgap"])
def test_chd_resource_growth_retimes_real_q_by_cd_frames_not_chd_padding_and_verifies_output(tmp_path, gap):
    source = prepared_source(tmp_path, gap)
    picked = detect.identify(source)
    image, segments = joined(picked)
    root = tmp_path / "export"
    root.mkdir()
    original = psx_media.snapshot(source, picked, root)
    layout = psx_disc.bind(picked.disc, segments, image)
    meta = {"platform": "psx", "disc": {"image": original.name, "layout": layout}}
    (root / "build.json").write_text(json.dumps(meta))
    output = root / "build/psx-mod/disc.chd"
    output.parent.mkdir(parents=True)
    shutil.copyfile(original, output)
    replacement = tmp_path / "resource.bin"
    replacement.write_bytes(b"original new resource".ljust(9000, b"!"))
    psx_assets.stage(root, "MUSIC.VAB", replacement, relocate=True)
    report = psx_assets.apply(root, meta, output)
    psx_assets.verify(root, meta, output, report)
    assert report["data_frames"] == 37 and report["insert_frames"] == 8
    with Chd(original) as before, Chd(output) as after:
        before.seek(32 * 2448)
        after.seek(40 * 2448)
        old, new = before.read(), after.read()
    assert len(old) == len(new)
    for offset in range(0, len(old), 2448):
        assert old[offset:offset + 2352] == new[offset:offset + 2352]
        old_raw, new_raw = old[offset + 2352:offset + 2448], new[offset + 2352:offset + 2448]
        assert bytes(b & 0xBF for b in old_raw) == bytes(b & 0xBF for b in new_raw)
        if not any(old_raw):
            assert not any(new_raw)
            continue
        old_q, new_q = separated(old_raw), separated(new_raw)
        assert new_q[10:] == check_bytes(new_q[:10])
        if old_q[0] == 1:
            assert new_q[:7] == old_q[:7]
            assert psx_subcode.position(new_q[7:10]) - psx_subcode.position(old_q[7:10]) == 7
        else:
            assert new_q[:9] == old_q[:9]
            assert psx_subcode.bcd(new_q[9], 75) == (psx_subcode.bcd(old_q[9], 75) + 7) % 75
    # A valid CHD hash alone cannot substitute for unchanged audio bytes.
    damaged = tmp_path / "damaged.chd"
    rewrite(output, damaged, {40 * 2448: b"wrong audio"})
    with pytest.raises(RomError, match="audio"):
        psx_assets.verify(root, meta, damaged, report | {"output_size": damaged.stat().st_size})
