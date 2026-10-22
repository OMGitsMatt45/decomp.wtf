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
    bss_address: int | None = None


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
        self.arm7_program_size = self.modules["arm7"].stored_size
        self._arm7_autoloads()
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

    def _arm7_autoloads(self):
        """Recognize referenced Nitro-style ARM7 module parameters, never guess load addresses.

        ARM7's header covers the loader, copied blocks and descriptor table. Code
        inside a copied block must be recovered at its destination, not its file
        loading address. Unknown startup layouts remain a single retained module.
        """
        from dataclasses import replace

        main = self.modules["arm7"]
        code = self.data[main.offset:main.offset + main.stored_size]
        candidates = {}
        # SDK loaders reference the parameter block through ARM PC-relative ldr.
        for at in range(0, min(len(code) - 3, 0x200), 4):
            word = struct.unpack_from("<I", code, at)[0]
            if word & 0x0F7F0000 != 0x051F0000:  # ldr Rd,[pc,+/-imm12]
                continue
            literal = at + 8 + ((word & 0xFFF) if word & 0x800000 else -(word & 0xFFF))
            if literal < 0 or literal + 4 > len(code):
                continue
            params = struct.unpack_from("<I", code, literal)[0] - main.address
            if params < 0 or params % 4 or params + 20 > min(len(code), 0x1000):
                continue
            start, end, source, bss_start, bss_end = struct.unpack_from("<5I", code, params)
            lo, hi, loaded = start - main.address, end - main.address, source - main.address
            if not (0 <= loaded <= lo < hi <= len(code) and (hi - lo) % 12 == 0 and hi - lo <= 12 * 64):
                continue
            if not 0x02000000 <= bss_start <= bss_end <= 0x04000000:
                continue
            blocks, cursor = [], loaded
            for pos in range(lo, hi, 12):
                address, size, bss = struct.unpack_from("<3I", code, pos)
                if not (0 < size <= MAX_MODULE_SIZE and cursor + size <= lo and address % 4 == 0
                        and 0x02000000 <= address < address + size + bss <= 0x04000000):
                    break
                blocks.append((address, size, bss, cursor))
                cursor += size
            else:
                if cursor == lo and loaded >= params + 20:
                    candidates[params] = (loaded, bss_start, bss_end, blocks)
        if len(candidates) > 1:
            raise ValueError("ambiguous ARM7 autoload parameter blocks")
        if not candidates:
            return
        loaded, bss_start, bss_end, blocks = next(iter(candidates.values()))
        self.modules["arm7"] = replace(main, stored_size=loaded, code_size=loaded,
                                        bss_size=bss_end - bss_start, bss_address=bss_start)
        for index, (address, size, bss, cursor) in enumerate(blocks):
            name = f"arm7:autoload{index}"
            self.modules[name] = Module(name, "arm7", main.offset + cursor, size, address, size, bss)

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
                "arm7_header_program_size": self.arm7_program_size, "modules": modules}
