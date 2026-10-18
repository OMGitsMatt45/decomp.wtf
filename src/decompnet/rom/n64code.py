"""N64 overlay detection and compressed-code analysis, implemented in native C++."""

from . import _n64_native as native

JR_RA = 0x03E00008
BLOCK = 0x400
REGIONS = ((0x80000000, 0x81000000), (0x70000000, 0x80000000))


def _frame(word: int) -> bool:
    return bool(native.library().n64_frame(word))


def _place(rom, lo, hi, floor, calls, known=(), regions=REGIONS):
    """Shared code placement used by the PlayStation overlay importer too."""
    return native.place(rom, lo, hi, floor, calls, known, regions)


def find_segments(rom: bytes, taken: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Find (ROM start, ROM end, VRAM) of code outside known segments."""
    return native.find_segments(rom, taken)


def yaz0(data: bytes) -> bytes:
    """Decode Nintendo Yaz0, validating every back-reference in C++."""
    return native.yaz0(data)


def unpack_code(rom: bytes) -> list[tuple[int, bytes]]:
    """Find compressed Rare/Nintendo code, joining adjacent packed pages."""
    return native.unpack(rom)
