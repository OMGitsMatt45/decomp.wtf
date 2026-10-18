"""Python boundary for the native C++ N64 analyzer; no analysis fallback."""

import ctypes as C
from contextlib import contextmanager
from functools import cache
from pathlib import Path
import platform
import sys
import zlib

import rabbitizer

Decoder = C.CFUNCTYPE(C.c_int, C.c_uint32)
Inflate = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t), C.POINTER(C.c_size_t))
Segment = C.c_int64 * 3
Range = C.c_int64 * 2


@Decoder
def _implemented(word):
    return int(rabbitizer.Instruction(word).isImplemented())


@cache
def library():
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    suffix = "dll" if system == "windows" else "dylib" if system == "macos" else "so"
    path = Path(__file__).resolve().parents[1] / "_native" / f"n64-{system}-{machine}.{suffix}"
    try:
        lib = C.CDLL(str(path))
    except OSError as error:
        raise RuntimeError(f"The native N64 analyzer could not load ({path.name}). Reinstall decomp.wtf or build native/n64 for this platform: {error}") from error
    signatures = {
        "abi": (C.c_uint, []), "error": (C.c_char_p, []), "free": (None, [C.c_void_p]),
        "frame": (C.c_int, [C.c_uint32]),
        "place": (C.c_void_p, [C.c_char_p, C.c_size_t, C.c_int64, C.c_int64, C.c_int64,
                              C.POINTER(C.c_int64), C.c_size_t, C.POINTER(Range), C.c_size_t,
                              C.POINTER(Range), C.c_size_t]),
        "bytes": (C.c_void_p, [C.c_void_p]), "size": (C.c_size_t, [C.c_void_p]),
        "format": (C.c_int, [C.c_void_p]), "header": (C.POINTER(C.c_uint32), [C.c_void_p]),
        "segment_count": (C.c_size_t, [C.c_void_p]), "segments": (C.POINTER(Segment), [C.c_void_p]),
        "block_count": (C.c_size_t, [C.c_void_p]),
        "block_offset": (C.c_size_t, [C.c_void_p, C.c_size_t]),
        "block_size": (C.c_size_t, [C.c_void_p, C.c_size_t]),
        "block_bytes": (C.c_void_p, [C.c_void_p, C.c_size_t]),
        "normalize": (C.c_void_p, [C.c_char_p, C.c_size_t]),
        "inspect": (C.c_void_p, [C.c_char_p, C.c_size_t, Decoder]),
        "guess": (C.c_int, [C.c_char_p, C.c_size_t, Decoder]),
        "find_segments": (C.c_void_p, [C.c_char_p, C.c_size_t, C.POINTER(Segment), C.c_size_t]),
        "yaz0": (C.c_void_p, [C.c_char_p, C.c_size_t]),
        "unpack": (C.c_void_p, [C.c_char_p, C.c_size_t, Inflate]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(lib, "n64_" + name)
        function.restype, function.argtypes = result, args
    if lib.n64_abi() != 1:
        raise RuntimeError("The native N64 analyzer has an incompatible ABI; reinstall decomp.wtf")
    return lib


@contextmanager
def result(pointer):
    lib = library()
    if not pointer:
        raise ValueError(lib.n64_error().decode("utf-8", errors="replace"))
    try:
        yield pointer
    finally:
        lib.n64_free(pointer)


def normalize(data, inspect=False):
    lib = library()
    pointer = lib.n64_inspect(data, len(data), _implemented) if inspect else lib.n64_normalize(data, len(data))
    with result(pointer) as value:
        rom = C.string_at(lib.n64_bytes(value), lib.n64_size(value))
        header = list(lib.n64_header(value)[:5]) if inspect else None
        return rom, ("z64", "v64", "n64")[lib.n64_format(value)], header


def guess(data):
    if len(data) % 4:
        raise ValueError("N64 instruction scan length must be a multiple of four bytes")
    return "IDO" if library().n64_guess(data, len(data), _implemented) else "KMC"


def find_segments(data, taken):
    lib = library()
    ranges = (Segment * len(taken))(*(Segment(*segment) for segment in taken))
    with result(lib.n64_find_segments(data, len(data), ranges, len(taken))) as value:
        segments = lib.n64_segments(value)
        return [tuple(segments[index]) for index in range(lib.n64_segment_count(value))]


def place(data, lo, hi, floor, calls, known, regions):
    lib = library()
    targets = (C.c_int64 * len(calls))(*calls)
    occupied = (Range * len(known))(*(Range(*item) for item in known))
    allowed = (Range * len(regions))(*(Range(*item) for item in regions))
    with result(lib.n64_place(data, len(data), lo, hi, floor, targets, len(calls),
                             occupied, len(known), allowed, len(regions))) as value:
        if lib.n64_segment_count(value):
            return (*lib.n64_segments(value)[0], lib.n64_header(value)[0])


def yaz0(data):
    lib = library()
    try:
        with result(lib.n64_yaz0(data, len(data))) as value:
            return C.string_at(lib.n64_bytes(value), lib.n64_size(value))
    except ValueError as error:
        raise IndexError(str(error)) from error


def unpack(data):
    lib = library()
    owner = [None]  # Keep callback storage alive until C++ copies it.

    @Inflate
    def inflate(address, size, length, consumed):
        try:
            decoder = zlib.decompressobj(-15)
            output = decoder.decompress(C.string_at(address, size), 0x1000000)
            if not decoder.eof:
                return None
            owner[0] = C.create_string_buffer(output)
            length[0], consumed[0] = len(output), size - len(decoder.unused_data)
            return C.addressof(owner[0])
        except zlib.error:
            return None

    with result(lib.n64_unpack(data, len(data), inflate)) as value:
        return [(lib.n64_block_offset(value, index),
                 C.string_at(lib.n64_block_bytes(value, index), lib.n64_block_size(value, index)))
                for index in range(lib.n64_block_count(value))]
