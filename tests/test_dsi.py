"""Original TWL containers: structural parsing and opaque byte preservation."""

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from decompnet.forks.scratch_dsd import crc16
from decompnet.rom import dsi


def image(unit=2, modcrypt=True):
    data = bytearray(0xA000)
    data[:12], data[12:16], data[0x12], data[0x1C] = b"ORIGINAL TWL", b"ATWE", unit, 3 if modcrypt else 1
    struct.pack_into("<II", data, 0x80, 0x6000, 0x4000)
    for at, offset, size, load in ((0x20, 0x4000, 0x1000, 0x02000000), (0x30, 0x5000, 0x1000, 0x02380000),
                                   (0x1C0, 0x6000, 0x1000, 0x02008000), (0x1D0, 0x7000, 0x1000, 0x02390000)):
        struct.pack_into("<4I", data, at, offset, 0 if at >= 0x1C0 else load, load, size)
        data[offset:offset+size] = hashlib.shake_256(str(at).encode()).digest(size)
    for at, start, size in ((0x1E0, 0x4000, 0x2000), (0x1E8, 0x6000, 0x2000), (0x1F0, 0x8000, 0x100),
                             (0x1F8, 0x8100, 0x100), (0x220, 0x6000, 0x800), (0x228, 0x7000, 0x800)):
        struct.pack_into("<II", data, at, start, size)
    struct.pack_into("<I", data, 0x210, len(data))
    data[0x300:0x3B4] = bytes(range(180))
    data[0xF80:0x1000] = bytes(range(128))
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    return data


@pytest.mark.parametrize("unit", [2, 3])
@pytest.mark.parametrize("modcrypt", [False, True])
def test_stored_twl_programs_and_authentication_header_survive(tmp_path, unit, modcrypt):
    rom, output = tmp_path / "original.dsi", tmp_path / "stored"
    original = bytes(image(unit, modcrypt))
    rom.write_bytes(original)
    info = dsi.extract_stored(rom, output)
    assert info["kind"] == ("enhanced" if unit == 2 else "exclusive")
    assert not info["authentication_verified"] and info["header_crc_valid"]
    assert info["modcrypt_enabled"] == modcrypt
    assert (output / "header.stored.bin").read_bytes() == original[:0x4000]
    for name, at in (("arm9i", 0x6000), ("arm7i", 0x7000)):
        region = next(r for r in info["regions"] if r["name"] == name)
        assert region["entrypoint"] is None and region["modcrypted"] == modcrypt
        assert (output / region["file"]).read_bytes() == original[at:at+0x1000]
    assert json.loads((output / "container.json").read_text()) == info
    assert rom.read_bytes() == original
    with pytest.raises(FileExistsError):
        dsi.extract_stored(rom, output)


@pytest.mark.parametrize("field", [0x20, 0x30, 0x1C0, 0x1D0, 0x1E0, 0x1E8, 0x1F0, 0x1F8, 0x220, 0x228])
def test_out_of_file_ranges_fail_without_an_output_directory(tmp_path, field):
    data = image()
    struct.pack_into("<I", data, field, len(data) - 4)
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    rom = tmp_path / "invalid.dsi"
    rom.write_bytes(data)
    output = tmp_path / "stored"
    with pytest.raises(ValueError, match="range"):
        dsi.extract_stored(rom, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".twl-extract-*"))


@pytest.mark.parametrize("change,diagnostic", [("truncated", "truncated"), ("crc", "checksum"),
                                              ("unit", "DSi"), ("size", "image size"),
                                              ("header", "header size"), ("entry", "entrypoint")])
def test_invalid_header_metadata_is_rejected(change, diagnostic):
    data = image()
    if change == "truncated": data = data[:0xFFF]
    elif change == "crc": data[0] ^= 1
    elif change == "unit": data[0x12] = 0
    elif change == "size": struct.pack_into("<I", data, 0x210, len(data) + 1)
    elif change == "header": struct.pack_into("<I", data, 0x84, 0x200)
    elif change == "entry": struct.pack_into("<I", data, 0x24, 0x01000000)
    if change not in ("crc", "truncated"):
        struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    with pytest.raises(ValueError, match=diagnostic):
        dsi.parse_header(data[:0x1000], len(data))


def test_interrupted_publish_leaves_no_partial_output_or_changed_input(tmp_path, monkeypatch):
    rom, output = tmp_path / "original.dsi", tmp_path / "stored"
    original = bytes(image())
    rom.write_bytes(original)
    real_rename = Path.rename

    def interrupted(stage, target):
        if target == output:
            if os.name != "nt":
                assert stage.stat().st_mode & 0o077 == 0
                assert all(p.stat().st_mode & 0o077 == 0 for p in stage.iterdir())
            raise OSError("simulated publish interruption")
        return real_rename(stage, target)

    monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(OSError, match="interruption"):
        dsi.extract_stored(rom, output)
    assert not output.exists() and not list(tmp_path.glob(".twl-extract-*"))
    assert rom.read_bytes() == original


def test_inspection_cli_reports_stored_encryption_without_creating_files(tmp_path):
    rom = tmp_path / "original.dsi"
    original = bytes(image())
    rom.write_bytes(original)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "tools/dsi_inspect.py"), str(rom)],
                            capture_output=True, text=True, cwd=root)
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["platform"] == "dsi" and info["modcrypt_enabled"]
    assert not info["authentication_verified"]
    assert list(tmp_path.iterdir()) == [rom] and rom.read_bytes() == original
