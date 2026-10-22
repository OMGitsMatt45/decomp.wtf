"""Preserve an explicitly decrypted DS input without applying secure-area encryption."""

import shutil
import struct
from pathlib import Path

SECURE_MARKER = bytes.fromhex("ffdeffe7ffdeffe7")


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def header(path):
    with Path(path).open("rb") as stream:
        data = stream.read(0x200)
    if len(data) != 0x200 or crc16(data[:0x15E]) != struct.unpack_from("<H", data, 0x15E)[0]:
        raise ValueError("invalid or truncated DS header")
    if data[0x12] or data[0x1C] & 3:
        raise ValueError("TWL containers require the separate DSi workflow")
    return data


def stage_decrypted(source, target):
    """Defeat dsd's content heuristic on a private staging copy, then restore all supplied bytes."""
    data = header(source)
    offset, entry, address, size = struct.unpack_from("<4I", data, 0x20)
    if offset < 0x200 or size < 0x4000 or offset + size > Path(source).stat().st_size:
        raise ValueError("decrypted ARM9 extent is outside the ROM or lacks a full secure area")
    with Path(source).open("rb") as stream:
        stream.seek(offset)
        prefix = stream.read(0x800)
    shutil.copyfile(source, target)
    with Path(target).open("r+b") as stream:
        stream.seek(offset)
        stream.write(SECURE_MARKER)
    return prefix


def restore_prefix(extracted, prefix):
    import yaml

    config = yaml.safe_load((extracted / "config.yaml").read_text(encoding="utf-8"))
    arm9 = (extracted / config["arm9_bin"]).resolve()
    if extracted.resolve() not in arm9.parents or arm9.stat().st_size < len(prefix):
        raise ValueError("invalid extracted ARM9 path or size")
    with arm9.open("r+b") as stream:
        stream.write(prefix)


def retain_secure_crc(rom, reference):
    """Serialize retained secure CRC metadata and compute the new header CRC normally.

    No comparison exceptions: the caller still checks every rebuilt byte against
    its reference. The two fields are unavailable in dsd's header YAML format.
    """
    original, built = header(reference), header(rom)
    if built[12:16] != original[12:16]:
        raise ValueError("rebuilt game ID differs from decrypted reference")
    data = bytearray(built)
    data[0x6C:0x6E] = original[0x6C:0x6E]
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    with Path(rom).open("r+b") as stream:
        stream.write(data)
