"""N64 ROM images: byte order, header, and a first guess at the compiler.

Only facts read from the user's own file. Nothing here identifies a game against a database.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from . import _n64_native as native

MAGIC = {
    b"\x80\x37\x12\x40": "z64",  # big-endian, the native byte order
    b"\x37\x80\x40\x12": "v64",  # 16-bit byte-swapped (Doctor V64)
    b"\x40\x12\x37\x80": "n64",  # 32-bit little-endian
}
REGIONS = {
    "A": "All regions", "B": "Brazil", "C": "China", "D": "Germany", "E": "North America", "F": "France",
    "G": "Gateway 64 (NTSC)", "H": "Netherlands", "I": "Italy", "J": "Japan", "K": "Korea", "L": "Gateway 64 (PAL)",
    "N": "Canada", "P": "Europe", "S": "Spain", "U": "Australia", "W": "Scandinavia", "X": "Europe", "Y": "Europe",
}
MIN_SIZE = 0x40000  # 256 KiB: smaller than any cartridge, but leaves room for homebrew
MAX_SIZE = 64 * 1024 * 1024


class RomError(ValueError):
    pass


@dataclass
class RomInfo:
    title: str
    game_code: str
    region: str
    version: int
    entrypoint: int
    crc1: int
    crc2: int
    size: int
    sha1: str
    byte_order: str  # the format the file came in; we always work on z64
    compiler_guess: str  # "IDO" or "KMC"

    def to_dict(self) -> dict:
        return asdict(self)


def to_z64(data: bytes) -> tuple[bytes, str]:
    """Normalize a ROM image to big-endian (z64) and report the byte order it came in."""
    try:
        rom, fmt, _ = native.normalize(data)
        return rom, fmt
    except ValueError as error:
        raise RomError(str(error)) from error


def _text(raw: bytes) -> str:
    for enc in ("ascii", "shift_jis"):
        try:
            return raw.decode(enc).rstrip("\0 ").strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1").rstrip("\0 ").strip()


def guess_compiler(rom: bytes, start: int = 0x1000, limit: int = 0x100000) -> str:
    """IDO prefers `b` (beq $zero, $zero) for unconditional jumps inside functions; GCC (KMC) uses `j`.
    The same heuristic splat uses; good enough to pick a default the user can change."""
    return native.guess(rom[start:min(len(rom), start + limit)])


def read_info(data: bytes) -> tuple[bytes, RomInfo]:
    """(z64 bytes, header info) for a ROM image, or RomError with a message for the user."""
    try:
        rom, fmt, header = native.normalize(data, inspect=True)
    except ValueError as error:
        raise RomError(str(error)) from error
    entry, crc1, crc2, version, compiler = header
    code = _text(rom[0x3B:0x3F])
    info = RomInfo(
        title=_text(rom[0x20:0x34]) or "Untitled",
        game_code=code,
        region=REGIONS.get(code[3:4], "Unknown region") if len(code) == 4 else "Unknown region",
        version=version,
        entrypoint=entry,
        crc1=crc1,
        crc2=crc2,
        size=len(rom),
        sha1=hashlib.sha1(rom).hexdigest(),
        byte_order=fmt,
        compiler_guess="IDO" if compiler else "KMC",
    )
    return rom, info
