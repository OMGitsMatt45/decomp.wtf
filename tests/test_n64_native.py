"""Differential checks against the pre-rewrite Python implementation."""

import random
import struct
import zlib

import pytest

from decompnet.rom import _n64_native as native, n64, n64code
from .fixtures import n64_reference as original, n64code_reference as original_code
from .test_n64code import _code


def test_native_library_has_the_expected_abi():
    assert native.library().n64_abi() == 1


@pytest.mark.parametrize("order", ["z64", "v64", "n64"])
def test_header_and_byte_order_match_the_original(order):
    image = bytearray(0x40000)
    image[:4] = b"\x80\x37\x12\x40"
    image[8:12] = (0x80000400).to_bytes(4, "big")
    image[0x20:0x34] = b"C++ N64 ANALYZER    "[:20]
    image[0x3B:0x3F] = b"NATE"
    image[0x3F] = 3
    image[0x1000:0x1080] = struct.pack(">32I", *([0x10000003, 0, 0x0C000100, 0] * 8))
    if order == "v64":
        image[::2], image[1::2] = image[1::2], image[::2]
    elif order == "n64":
        image = bytearray().join(image[at:at + 4][::-1] for at in range(0, len(image), 4))
    actual, info = n64.read_info(bytes(image))
    expected, reference = original.read_info(bytes(image))
    assert actual == expected
    assert info.to_dict() == reference.to_dict()


@pytest.mark.parametrize("data", [b"", b"x" * 0x40000, b"\x80\x37\x12\x40" + b"\0" * 0x40000])
def test_invalid_images_keep_the_original_error(data):
    with pytest.raises(original.RomError) as old:
        original.read_info(data)
    with pytest.raises(n64.RomError) as new:
        n64.read_info(data)
    assert str(new.value) == str(old.value)


def test_compiler_guess_uses_the_same_decoder_stop_point():
    randomizer = random.Random(451)
    for _ in range(80):
        words = [randomizer.choice([0, 0x10000000, 0x10000002, 0x08000100, 0x0C000100, 0x03E00008, 0xFFFFFFFF]) for _ in range(128)]
        data = struct.pack(">128I", *words)
        assert n64.guess_compiler(data, 0, len(data)) == original.guess_compiler(data, 0, len(data))


@pytest.mark.parametrize("count", [8, 16, 40, 80, 120, 160])
@pytest.mark.parametrize("address", [0x80300000, 0x7F000000])
def test_segment_placement_matches_the_original(count, address):
    image = bytearray(0x80000)
    main = _code(0x80000400, 40, calls_into=address)
    image[0x1000:0x1000 + len(main)] = main
    extra = _code(address, count)
    image[0x50000:0x50000 + len(extra)] = extra
    taken = [(0x1000, 0x1000 + len(main), 0x80000400)]
    assert n64code.find_segments(bytes(image), taken) == original_code.find_segments(bytes(image), taken)


def test_packed_pages_and_false_markers_match_the_original():
    code = _code(0x7F000000, 256)
    image = bytearray(0x1000)
    image[0x40:0x50] = b"\x11\x73not deflate!"
    for at in range(0, len(code), 0x1000):
        page = code[at:at + 0x1000]
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = compressor.compress(page) + compressor.flush()
        image.extend(b"\x11\x73" + len(page).to_bytes(3, "big") + packed)
    data = bytes(image)
    assert n64code.unpack_code(data) == original_code.unpack_code(data)


def test_yaz0_matches_and_rejects_invalid_references():
    valid = b"Yaz0" + (9).to_bytes(4, "big") + bytes(8) + b"\xe0abc\x40\x02"
    assert n64code.yaz0(valid) == original_code.yaz0(valid)
    for invalid in [b"", b"Yaz0" + (40).to_bytes(4, "big") + bytes(8) + b"\0\x40\x02"]:
        with pytest.raises(IndexError):
            n64code.yaz0(invalid)


def test_segment_inputs_cannot_read_outside_the_rom():
    with pytest.raises(ValueError, match="inside the ROM"):
        n64code.find_segments(bytes(0x1000), [(0x1000, 0x2000, 0x80000000)])
