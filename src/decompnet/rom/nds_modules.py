"""Read DS module boundaries without decrypting the secure area or modifying the ROM."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from ..forks.scratch_dsd import crc16
from .dsprot import detect

MAX_MODULE_SIZE = 32 * 1024 * 1024


def decompress_blz(data: bytes, expected: int) -> bytes:
    """Bounded Nintendo backwards LZ decoding, including its unchanged prefix."""
    if len(data) < 8 or not 0 < expected <= MAX_MODULE_SIZE:
        raise ValueError("invalid BLZ size")
    total = int.from_bytes(data[-8:-5], "little")
    header = data[-5]
    extra = int.from_bytes(data[-4:], "little")
    if not 8 <= header <= total <= len(data) or len(data) + extra != expected:
        raise ValueError("invalid BLZ footer or expanded size")
    prefix = len(data) - total
    pos = len(data) - header
    reverse = bytearray()

    def take():
        nonlocal pos
        if pos <= prefix:
            raise ValueError("truncated BLZ token")
        pos -= 1
        return data[pos]

    while pos > prefix:
        flags = take()
        for bit in range(7, -1, -1):
            if flags & (1 << bit):
                pair = (take() << 8) | take()
                distance, length = (pair & 0xFFF) + 3, (pair >> 12) + 3
                if distance > len(reverse) or length > distance:
                    raise ValueError("BLZ backreference outside decoded data")
                start = len(reverse) - distance
                reverse.extend(reverse[start:start + length])
            else:
                reverse.append(take())
            if prefix + len(reverse) > expected:
                raise ValueError("BLZ output exceeds expanded size")
            if pos == prefix:
                break
    if prefix + len(reverse) != expected:
        raise ValueError("BLZ output differs from expanded size")
    return data[:prefix] + bytes(reversed(reverse))


@dataclass(frozen=True)
class Module:
    name: str
    cpu: str
    offset: int
    stored_size: int
    address: int
    code_size: int
    bss_size: int = 0
    overlay_id: int | None = None
    file_id: int | None = None
    ctor_start: int = 0
    ctor_end: int = 0
    flags: int = 0


class NdsImage:
    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 0x200:
            raise ValueError("truncated DS header")
        if data[0x12] or data[0x1C] & 3:
            raise ValueError("TWL containers need the separate DSi inspector")
        if crc16(data[:0x15E]) != struct.unpack_from("<H", data, 0x15E)[0]:
            raise ValueError("invalid DS header CRC")
        self.modules: dict[str, Module] = {}
        for cpu, at in (("arm9", 0x20), ("arm7", 0x30)):
            offset, entry, address, size = struct.unpack_from("<4I", data, at)
            self._range(offset, size)
            self._address(address, size)
            if not address <= (entry & ~1) < address + size:
                raise ValueError(f"{cpu} entrypoint outside program")
            self.modules[cpu] = Module(cpu, cpu, offset, size, address, size)
        fat_offset, fat_size = struct.unpack_from("<2I", data, 0x48)
        self._range(fat_offset, fat_size, empty=True)
        if fat_size % 8:
            raise ValueError("FAT size is not a multiple of 8")
        for cpu, at in (("arm9", 0x50), ("arm7", 0x58)):
            offset, size = struct.unpack_from("<2I", data, at)
            self._range(offset, size, empty=True)
            if size % 32:
                raise ValueError("overlay table size is not a multiple of 32")
            for pos in range(offset, offset + size, 32):
                oid, address, code, bss, start, end, fid, flags = struct.unpack_from("<8I", data, pos)
                name = f"{cpu}:ov{oid}"
                if name in self.modules:
                    raise ValueError(f"duplicate overlay ID: {name}")
                if fid >= fat_size // 8:
                    raise ValueError(f"{name}: file ID outside FAT")
                lo, hi = struct.unpack_from("<2I", data, fat_offset + fid * 8)
                self._range(lo, hi - lo)
                self._address(address, code + bss)
                if code <= 0 or code > MAX_MODULE_SIZE:
                    raise ValueError(f"{name}: invalid code size")
                if (start or end) and not address <= start <= end <= address + code:
                    raise ValueError(f"{name}: constructors outside initialized module")
                self.modules[name] = Module(name, cpu, lo, hi - lo, address, code, bss,
                                            oid, fid, start, end, flags)

    @classmethod
    def read(cls, path: Path) -> NdsImage:
        return cls(path.read_bytes())

    def _range(self, offset: int, size: int, *, empty=False):
        if size == 0 and empty and 0 <= offset <= len(self.data):
            return
        if offset < 0x200 or size <= 0 or offset + size > len(self.data):
            raise ValueError("module or table outside ROM")

    @staticmethod
    def _address(address: int, size: int):
        if size <= 0 or address + size > 0x100000000:
            raise ValueError("module exceeds 32-bit address space")

    def code(self, name: str) -> bytes:
        try:
            module = self.modules[name]
        except KeyError:
            raise ValueError(f"unknown module: {name}") from None
        if name == "arm9":
            raise ValueError("ARM9 main requires secure-area and compression decoding in the DS importer")
        stored = self.data[module.offset:module.offset + module.stored_size]
        if module.overlay_id is None:
            return stored  # the ARM7 header describes an uncompressed program
        if module.flags & 0xFC000000:
            raise ValueError("unknown overlay flags require layout support")
        if module.flags & 0x1000000:
            if module.flags & 0xFFFFFF != len(stored):
                raise ValueError("compressed overlay size differs from FAT extent")
            return decompress_blz(stored, module.code_size)
        if len(stored) != module.code_size:
            raise ValueError("uncompressed overlay size differs from initialized size")
        return stored

    def inspect(self) -> dict:
        modules = []
        for module in self.modules.values():
            item = {**asdict(module), "signed": bool(module.flags & 0x2000000),
                    "authentication_verified": False}
            try:
                code = self.code(module.name)
            except ValueError as error:
                item.update(decoded=False, reason=str(error))
            else:
                item.update(decoded=True, sha256=hashlib.sha256(code).hexdigest(),
                            ds_protect_candidates=detect(code, module.address))
            modules.append(item)
        return {"id": self.data[12:16].decode("ascii", "replace"), "revision": self.data[0x1E],
                "bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(),
                "secure_area_validated": False, "bios_required_for_inspection": False,
                "modules": modules}
