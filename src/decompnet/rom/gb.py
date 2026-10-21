"""Bank-aware Game Boy / Game Boy Color cartridge inspection and code discovery.

Storage banks are kept distinct even when they share CPU addresses $4000-$7fff.
Discovery is a starting point for a disassembly, not proof that bytes are code or
that a game was originally written in any particular source language.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import asdict, dataclass

from . import sm83

BANK_SIZE = 0x4000
LOGO = bytes.fromhex(
    "ce ed 66 66 cc 0d 00 0b 03 73 00 83 00 0c 00 0d "
    "00 08 11 1f 88 89 00 0e dc cc 6e e6 dd dd d9 99 "
    "bb bb 67 63 6e 0e ec cc dd dc 99 9f bb b9 33 3e")
_MAPPERS = {0: "ROM ONLY", 1: "MBC1", 2: "MBC1+RAM", 3: "MBC1+RAM+BATTERY",
            5: "MBC2", 6: "MBC2+BATTERY", 8: "ROM+RAM", 9: "ROM+RAM+BATTERY",
            0x0B: "MMM01", 0x0C: "MMM01+RAM", 0x0D: "MMM01+RAM+BATTERY",
            0x0F: "MBC3+TIMER+BATTERY", 0x10: "MBC3+TIMER+RAM+BATTERY",
            0x11: "MBC3", 0x12: "MBC3+RAM", 0x13: "MBC3+RAM+BATTERY",
            0x19: "MBC5", 0x1A: "MBC5+RAM", 0x1B: "MBC5+RAM+BATTERY",
            0x1C: "MBC5+RUMBLE", 0x1D: "MBC5+RUMBLE+RAM", 0x1E: "MBC5+RUMBLE+RAM+BATTERY",
            0x20: "MBC6", 0x22: "MBC7+SENSOR+RUMBLE+RAM+BATTERY", 0xFC: "POCKET CAMERA",
            0xFD: "BANDAI TAMA5", 0xFE: "HuC3", 0xFF: "HuC1+RAM+BATTERY"}


class CartridgeError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Address:
    bank: int
    cpu: int

    def __post_init__(self):
        if not 0 <= self.bank < 512 or not (0 <= self.cpu < BANK_SIZE if self.bank == 0 else
                                           BANK_SIZE <= self.cpu < BANK_SIZE * 2):
            raise CartridgeError("use bank 0 at $0000-$3fff or banks 1-$1ff at $4000-$7fff")

    @property
    def offset(self) -> int:
        return self.bank * BANK_SIZE + self.cpu % BANK_SIZE

    @property
    def key(self) -> int:
        """Unique address in the coordination database; not a CPU pointer."""
        return self.bank << 16 | self.cpu

    @classmethod
    def from_key(cls, key: int) -> Address:
        return cls(key >> 16, key & 0xFFFF)

    @classmethod
    def from_offset(cls, offset: int) -> Address:
        if offset < 0:
            raise CartridgeError("negative ROM offset")
        bank, within = divmod(offset, BANK_SIZE)
        return cls(bank, within + (BANK_SIZE if bank else 0))

    @classmethod
    def parse(cls, text: str) -> Address:
        try:
            bank, cpu = text.split(":")
            return cls(int(bank, 16), int(cpu, 16))
        except (ValueError, TypeError) as error:
            raise CartridgeError(f"invalid bank:address {text!r}; use hexadecimal, e.g. 02:4000") from error

    def __str__(self) -> str:
        return f"{self.bank:02x}:{self.cpu:04x}"


@dataclass(frozen=True)
class CodeRange:
    start: Address
    size: int

    def __post_init__(self):
        if self.size <= 0 or self.start.cpu % BANK_SIZE + self.size > BANK_SIZE:
            raise CartridgeError("a code range must be nonempty and stay inside one storage bank")

    def to_dict(self) -> dict:
        return {**asdict(self.start), "offset": self.start.offset, "size": self.size}

    @classmethod
    def parse(cls, text: str) -> CodeRange:
        try:
            bank, start, end = text.split(":")
            address = Address.parse(f"{bank}:{start}")
            size = int(end, 16) - int(start, 16)
        except CartridgeError:
            raise
        except ValueError as error:
            raise CartridgeError(f"invalid range {text!r}; use hexadecimal bank:start:end (exclusive)") from error
        return cls(address, size)


def read_info(data: bytes) -> dict:
    if len(data) < 0x150 or data[0x104:0x134] != LOGO:
        raise CartridgeError("not a Game Boy / Game Boy Color cartridge header (Nintendo logo missing)")
    checksum = 0
    for value in data[0x134:0x14D]:
        checksum = (checksum - value - 1) & 255
    if checksum != data[0x14D]:
        raise CartridgeError("Game Boy header checksum does not match")
    size_code = data[0x148]
    banks = 2 << size_code if size_code <= 8 else {0x52: 72, 0x53: 80, 0x54: 96}.get(size_code)
    if banks is None:
        raise CartridgeError(f"unknown Game Boy ROM size code ${size_code:02x}")
    if len(data) != banks * BANK_SIZE:
        raise CartridgeError(f"header declares {banks} banks ({banks * BANK_SIZE} bytes), file has {len(data)} bytes")
    cgb = bool(data[0x143] & 0x80)
    title = data[0x134:0x13F if cgb else 0x144].split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
    global_checksum = int.from_bytes(data[0x14E:0x150], "big")
    return {"platform": "gbc" if cgb else "gb", "title": title, "size": len(data), "banks": banks,
            "arch": "sm83", "language": "asm", "cgb_only": data[0x143] == 0xC0,
            "cartridge_type": data[0x147], "mapper": _MAPPERS.get(data[0x147], f"Unknown ${data[0x147]:02x}"),
            "header_checksum_valid": True,
            "global_checksum_valid": (sum(data) - sum(data[0x14E:0x150])) & 0xFFFF == global_checksum,
            "sha256": hashlib.sha256(data).hexdigest()}


def resolve(origin: Address, cpu: int, info: dict) -> Address | None:
    """Resolve only a fixed bank or the current ROMX bank; never guess a switched bank from ROM0."""
    if 0 <= cpu < BANK_SIZE:
        return Address(0, cpu)
    if BANK_SIZE <= cpu < 2 * BANK_SIZE:
        bank = origin.bank
        if not bank and info["banks"] == 2 and info["cartridge_type"] in (0, 8, 9):
            bank = 1
        if bank:
            return Address(bank, cpu)
    return None


def discover(data: bytes, entries: list[Address] | None = None) -> tuple[list[CodeRange], list[str]]:
    """Follow direct control flow, with explicit extra entries for switched banks.

    Absolute mapper writes and unresolved jumps stop a path. Indirect calls,
    jump tables, interrupt installation, bank switches through registers, RAM
    execution and caller/callee bank effects need review; no emulator is supplied.
    """
    info = read_info(data)
    pending = deque(entries if entries is not None else [Address(0, 0x100)])
    instructions: dict[int, sm83.Instruction] = {}
    occupied: dict[int, int] = {}
    notes: set[str] = set()
    for entry in pending:
        if entry.offset >= len(data):
            raise CartridgeError(f"entry {entry} is beyond this cartridge")
        if entry.bank == 0 and 0x104 <= entry.cpu < 0x150:
            raise CartridgeError(f"entry {entry} is inside the cartridge header")
    while pending:
        addr = pending.popleft()
        offset = addr.offset
        if offset in instructions:
            continue
        if offset in occupied:
            notes.add(f"{addr}: branch enters an instruction operand; review the overlapping code")
            continue
        if addr.bank == 0 and 0x104 <= addr.cpu < 0x150:
            notes.add(f"{addr}: stopped at cartridge header")
            continue
        limit = (addr.bank + 1) * BANK_SIZE
        insn = sm83.decode(data[offset:min(offset + 3, limit)], addr.cpu)
        if insn.flow == "invalid":
            notes.add(f"{addr}: invalid or truncated instruction left in base ROM")
            continue
        if any(i in occupied for i in range(offset, offset + len(insn.data))):
            notes.add(f"{addr}: overlapping code paths; review required")
            continue
        if addr.bank == 0 and offset < 0x104 < offset + len(insn.data):
            notes.add(f"{addr}: instruction overlaps cartridge header")
            continue
        instructions[offset] = insn
        for i in range(offset, offset + len(insn.data)):
            occupied[i] = offset
        if insn.write is not None and insn.write < 0x8000 and info["cartridge_type"] not in (0, 8, 9):
            notes.add(f"{addr}: mapper write stops discovery; add the resulting bank entry explicitly")
            continue
        if insn.flow == "indirect":
            notes.add(f"{addr}: indirect jump target needs an explicit entry")
        destinations = []
        if insn.target is not None:
            destinations.append(insn.target)
        if insn.flow not in ("jump", "return", "indirect"):
            destinations.append((addr.cpu + len(insn.data)) & 0xFFFF)
        for cpu in destinations:
            dest = resolve(addr, cpu, info)
            if dest is None:
                notes.add(f"{addr}: ${cpu:04x} has no known ROM bank; add an explicit entry if it is code")
            elif dest.offset >= len(data):
                notes.add(f"{addr}: target {dest} is beyond this cartridge")
            else:
                pending.append(dest)
    ranges: list[CodeRange] = []
    for offset, insn in sorted(instructions.items()):
        if ranges and ranges[-1].start.offset + ranges[-1].size == offset and ranges[-1].start.bank == offset // BANK_SIZE:
            prev = ranges.pop()
            ranges.append(CodeRange(prev.start, prev.size + len(insn.data)))
        else:
            ranges.append(CodeRange(Address.from_offset(offset), len(insn.data)))
    return ranges, sorted(notes)


def assembly(data: bytes, region: CodeRange) -> str:
    if region.start.offset + region.size > len(data):
        raise CartridgeError("code range exceeds the cartridge")
    bank, cpu = region.start.bank, region.start.cpu
    name = f"code_{bank:03x}_{cpu:04x}"
    section = f"ROMX[${cpu:04x}], BANK[${bank:x}]" if bank else f"ROM0[${cpu:04x}]"
    raw = data[region.start.offset:region.start.offset + region.size]
    instructions = sm83.disassemble(raw, cpu)
    boundaries = {insn.address for insn in instructions}
    labels = {insn.target for insn in instructions if insn.target in boundaries}
    lines = [f'; Storage bank ${bank:03x}, CPU ${cpu:04x}, file offset ${region.start.offset:x}',
             f'SECTION "{name}", {section}', f"{name}::"]
    for insn in instructions:
        if insn.address in labels:
            lines.append(f".L{insn.address:04x}:")
        text = insn.text
        if insn.target in labels and not text.startswith("rst "):
            text = text.rsplit("$", 1)[0] + f".L{insn.target:04x}"
        # A JR at the CPU address wrap must keep its signed displacement, not
        # a wrapped absolute address that the linker sees as out of range.
        if text.startswith("jr ") and insn.target not in labels:
            displacement = int.from_bytes(insn.data[1:2], "little", signed=True) + 2
            prefix = text.rsplit("$", 1)[0]
            text = prefix + f"@{displacement:+d}"
        lines.append(f"    {text}")
    lines += [f'ASSERT @ == ${cpu + region.size:04x}, "{name} changed size"', ""]
    return "\n".join(lines)
