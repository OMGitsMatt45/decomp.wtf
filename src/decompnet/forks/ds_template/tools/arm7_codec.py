"""Use pinned ds-rom overlay codecs for ARM7 modules at their runtime addresses.

The small, original carrier is only a codec container. It contains no game code
except the supplied module. Neither the carrier nor decoded bytes are tracked.
Blank logo encoding: copyright 2025 Aetias, MIT; see ds-rom.LICENSE.
"""

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import yaml

try:
    from .nds_input import SECURE_MARKER, crc16
except ImportError:  # standalone exported project
    from nds_input import SECURE_MARKER, crc16


def carrier(code, address):
    if not code or len(code) % 4 or len(code) > 32 * 1024 * 1024 or not 0 <= address < address + len(code) <= 0x100000000:
        raise ValueError("invalid ARM7 codec module extent")
    # Blank logo encoding from ds-rom (MIT, ds-rom.LICENSE), also used by
    # the original DS fixture. This deliberately contains no console artwork.
    codes = [(1, 1), (4, 6), (5, 10), (4, 4), (5, 2), (6, 30), (6, 22), (6, 6),
             (5, 6), (6, 31), (6, 23), (6, 7), (4, 2), (5, 14), (5, 7), (4, 0)]
    bitmap = struct.pack("<I", 0xD082) + bytes(208) + struct.pack("<I", 0xFFF4C307)
    bits = "".join(format(codes[n][1], f"0{codes[n][0]}b") for b in bitmap for n in (b & 15, b >> 4))
    bits += "0" * (-len(bits) % 8)
    logo = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))[:156].ljust(156, b"\0")
    logo = b"".join(logo[i:i + 4][::-1] for i in range(0, 156, 4))
    data = bytearray(0xA000) + code
    data[:12], data[12:18] = b"DSCODEC\0\0\0\0\0", b"ACDE00"
    data[0xC0:0x15C] = logo
    data[0x4000:0x4008] = SECURE_MARKER
    struct.pack_into("<I", data, 0x4800, 0xE12FFF1E)
    struct.pack_into("<9I", data, 0x4810, *([0x02004000] * 5), 0, 0x04027531, 0xDEC00621, 0x2106C0DE)
    struct.pack_into("<3I", data, 0x8000, 0xDEC00621, 0x810, 0)
    struct.pack_into("<I", data, 0x8200, 0xE12FFF1E)
    struct.pack_into("<IHH", data, 0x8400, 8, 1, 1)
    struct.pack_into("<2I", data, 0x8600, 0xA000, len(data))
    struct.pack_into("<8I", data, 0x8800, 0, address, len(code), 0, 0, 0, 0, 0)
    struct.pack_into("<H", data, 0x8A00, 1)
    struct.pack_into("<4I", data, 0x20, 0x4000, 0x02000800, 0x02000000, 0x4000)
    struct.pack_into("<4I", data, 0x30, 0x8200, 0x02380000, 0x02380000, 4)
    struct.pack_into("<4I", data, 0x40, 0x8400, 9, 0x8600, 8)
    struct.pack_into("<2I", data, 0x50, 0x8800, 32)
    struct.pack_into("<I", data, 0x68, 0x8A00)
    capacity = max(0x20000, 1 << (len(data) - 1).bit_length())
    data[0x14] = (capacity // 0x20000).bit_length() - 1
    struct.pack_into("<2I", data, 0x80, len(data), 0x4000)
    struct.pack_into("<H", data, 0x15C, crc16(logo))
    struct.pack_into("<H", data, 0x15E, crc16(data[:0x15E]))
    return data


def run(dsd, *args):
    result = subprocess.run([str(dsd), "rom", *map(str, args)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise ValueError("ARM7 protection codec failed: " + (result.stdout + result.stderr)[-2000:])


def overlay(directory):
    config = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    table = directory / config["arm9_overlays"]
    item = yaml.load(table.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["overlays"][0]
    return item, table.parent / item["file_name"]


def encrypt(dsd, directory, code):
    with tempfile.TemporaryDirectory(prefix=".e-", dir=directory.parent) as temporary:
        work = Path(temporary)
        copied = work / "r"
        shutil.copytree(directory, copied)
        item, binary = overlay(copied)
        if len(code) != int(item["code_size"]):
            raise ValueError("ARM7 protected module changed size")
        binary.write_bytes(code)
        built = work / "encoded.nds"
        run(dsd, "build", "--config", copied / "config.yaml", "--rom", built)
        data = built.read_bytes()
        fat = struct.unpack_from("<I", data, 0x48)[0]
        lo, hi = struct.unpack_from("<2I", data, fat)
        if not 0 <= lo < hi <= len(data) or hi - lo != len(code):
            raise ValueError("ARM7 codec output has an invalid FAT extent")
        return data[lo:hi]


def decode(dsd, code, address, directory):
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".d-", dir=directory.parent) as temporary:
        work = Path(temporary)
        source = work / "carrier.nds"
        source.write_bytes(carrier(code, address))
        staged = work / "r"
        run(dsd, "extract", "--rom", source, "--output-path", staged)
        (staged / "files").mkdir(exist_ok=True)
        (staged / "files/codec.txt").write_text("Original ARM7 codec carrier.\n", encoding="utf-8")
        (staged / "path_order.txt").write_text("codec.txt\n", encoding="utf-8")
        # ds-rom's build schema requires both TCM files, including for a carrier
        # with no copied ARM9 blocks. Empty blocks are outside the codec payload.
        for name, base, kind in (("itcm", 0x01FF8000, "Itcm"), ("dtcm", 0x027E0000, "Dtcm")):
            (staged / "arm9" / (name + ".bin")).write_bytes(b"")
            (staged / "arm9" / (name + ".yaml")).write_text(yaml.safe_dump(
                {"base_address": base, "code_size": 0, "bss_size": 0, "kind": kind}), encoding="utf-8")
        item, binary = overlay(staged)
        state = item.get("dsprot", {}).get("unencrypted") if isinstance(item.get("dsprot"), dict) else None
        if state is None or int(item["base_address"]) != address:
            raise ValueError("ARM7 codec did not decode the protected runtime module")
        if not entries(state):
            raise ValueError("ARM7 signature has no codec-verified protected functions")
        plain = binary.read_bytes()
        if len(plain) != len(code) or encrypt(dsd, staged, plain) != code:
            raise ValueError("ARM7 protected module failed exact re-encryption")
        if directory.exists():
            shutil.rmtree(directory)
        staged.replace(directory)
    return plain, state


def entries(state):
    """Seed discovery with codec-verified protected ARM function boundaries."""
    return [int(r["start_address"]) for r in state.get("encrypted_ranges", [])] + [
        int(f["address"]) for f in state.get("functions", [])]
