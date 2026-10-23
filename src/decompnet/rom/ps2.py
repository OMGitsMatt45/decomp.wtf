"""PlayStation 2 programs: the game's main executable is an ELF for the Emotion Engine (e.g. SLUS_200.00 on the disc,
named by SYSTEM.CNF's BOOT2 line). Usually stripped, sometimes still with symbols."""

from __future__ import annotations

import hashlib
import re
import struct

from .errors import RomError
from .psx import region_of

EM_MIPS = 8


def is_mips_elf(data: bytes) -> bool:
    return len(data) > 0x34 and data[:4] == b"\x7fELF" and data[5] == 1 and struct.unpack_from("<H", data, 18)[0] == EM_MIPS


def read_elf(data: bytes, boot_name: str = "") -> tuple[bytes, dict]:
    if not is_mips_elf(data) or data[4] != 1:
        raise RomError("this isn't a PlayStation 2 program (expected a 32-bit little-endian MIPS ELF)")
    e_type, _, entry = struct.unpack_from("<HHI", data, 16)[0], 0, struct.unpack_from("<I", data, 24)[0]
    if e_type != 2:
        raise RomError("this ELF isn't an executable (it may be a library or an object file)")
    code = ""
    m = re.match(r"^([A-Z]{4})[_-](\d{3})\.?(\d{2})", boot_name.upper())
    if m:
        code = f"{m.group(1)}-{m.group(2)}{m.group(3)}"
    has_symbols = b".symtab" in data[-65536:] or b".symtab" in data[:65536]
    return data, {
        "title": code or boot_name or "PlayStation 2 game", "game_code": code, "region": region_of(code) if code else "Unknown region",
        "version": 0, "entrypoint": entry, "gp": 0, "crc1": 0, "crc2": 0, "size": len(data),
        "sha1": hashlib.sha1(data).hexdigest(), "byte_order": "elf", "compiler_guess": "EEGCC", "platform": "ps2",
        "boot": boot_name, "symbols": has_symbols,
    }


def bss_layout(config: dict, program: bytes) -> bool:
    """NOBITS ranges include the alignment gaps between .sbss and .bss."""
    from io import BytesIO
    from elftools.elf.elffile import ELFFile

    sections = [s for s in ELFFile(BytesIO(program)).iter_sections()
                if s["sh_type"] == "SHT_NOBITS" and s["sh_flags"] & 2 and s["sh_size"]]
    changed = False
    raw = config.get("segments", [])
    for i, segment in enumerate(raw):
        if not isinstance(segment, dict) or segment.get("type") != "code":
            continue
        starts = [s["vram"] for s in segment.get("subsegments", []) if isinstance(s, dict)
                  and s.get("type") in ("bss", "sbss") and "vram" in s]
        ends = [s["sh_addr"] + s["sh_size"] for s in sections if s["sh_addr"] in starts]
        rom_end = next((s[0] if isinstance(s, list) else s.get("start") for s in raw[i + 1:]), None)
        if starts and ends and rom_end is not None:
            # Splat measures bss_size from the loaded segment's end, including
            # the initial alignment gap before the first NOBITS section.
            size = max(ends) - (segment["vram"] + rom_end - segment["start"])
            changed |= segment.get("bss_size") != size
            segment["bss_size"] = size
    return changed


def rebuild_elf(program: bytes, original_flat: bytes, rebuilt_flat: bytes) -> bytes:
    """Put rebuilt allocated sections into the owner's original ELF envelope.

    objcopy uses section load addresses, which can differ from virtual addresses.
    Keep the original headers, file padding and nonallocated metadata verbatim.
    This rebuilds the main executable, not a disc image or separate overlays.
    """
    from io import BytesIO
    from elftools.elf.elffile import ELFFile

    elf = ELFFile(BytesIO(program))
    sections = []
    for section in elf.iter_sections():
        if not section["sh_flags"] & 2 or section["sh_type"] == "SHT_NOBITS" or not section["sh_size"]:
            continue
        address = section["sh_addr"]
        for segment in elf.iter_segments():
            if segment["p_type"] == "PT_LOAD" and segment.section_in_segment(section):
                address += segment["p_paddr"] - segment["p_vaddr"]
                break
        sections.append((section, address))
    if not sections or len(rebuilt_flat) != len(original_flat):
        raise ValueError("PS2 ELF payload has an incompatible layout or size")
    base = min(address for _, address in sections)
    result = bytearray(program)
    for section, address in sections:
        start, size = address - base, section["sh_size"]
        if original_flat[start:start + size] != section.data():
            raise ValueError(f"PS2 ELF section {section.name} does not match the original flat payload")
        offset = section["sh_offset"]
        result[offset:offset + size] = rebuilt_flat[start:start + size]
    return bytes(result)
