"""Original stripped callback bodies are recovered from bounded unwind metadata."""
import struct

import pytest

from decompnet.pc import PCError
from decompnet.switch_native import discovery


BASE = 0x7100010000


def original(*, data_relative=True):
    image = bytearray(0x3000)
    # The functions have no symbols, ADR references or relocated code pointers.
    struct.pack_into('<I', image, 4, 0x100)
    struct.pack_into('<4s6i', image, 0x100, b'MOD0', 0, 0, 0, 0xf00, 0xf1c, 0)
    struct.pack_into('<II', image, 0x200, 0x52800540, 0xd65f03c0)  # mov w0,42; ret
    struct.pack_into('<II', image, 0x240, 0x52800560, 0xd65f03c0)  # mov w0,43; ret
    image[0x1000:0x1004] = bytes((1, 0x1b, 3, 0x3b if data_relative else 0x1b))
    struct.pack_into('<iI', image, 0x1004, 0x1100 - 0x1004, 2)
    for i, function in enumerate((0x200, 0x240)):
        at = 0x100c + i * 8
        struct.pack_into('<ii', image, at,
                         function - (0x1000 if data_relative else at),
                         0x1100 + i * 8 - (0x1000 if data_relative else at + 4))
    inspection = dict(base=BASE, entry=BASE, segments=[
        dict(offset=0, size=0x400), dict(offset=0x1000, size=0x200), dict(offset=0x2000, size=0x80)])
    return image, inspection


@pytest.mark.parametrize('data_relative', [True, False])
def test_unreferenced_callbacks_have_exact_rebased_entries(data_relative):
    image, inspection = original(data_relative=data_relative)
    assert discovery.unwind_entries(image, inspection) == [BASE + 0x200, BASE + 0x240]
    assert discovery.entries(image, inspection) == [BASE, BASE + 0x200, BASE + 0x240]


@pytest.mark.parametrize('change', ['version', 'indirect', 'unknown-encoding', 'count',
    'truncated-table', 'outside-text', 'unaligned', 'unordered', 'outside-fde', 'outside-header',
    'missing-table', 'missing-count', 'relative-count', 'bss-header'])
def test_malformed_unwind_metadata_fails_before_translation(change):
    image, inspection = original()
    if change == 'version': image[0x1000] = 2
    elif change == 'indirect': image[0x1003] = 0xbb
    elif change == 'unknown-encoding': image[0x1003] = 0x39
    elif change == 'count': struct.pack_into('<I', image, 0x1008, 0xffffffff)
    elif change == 'truncated-table': struct.pack_into('<i', image, 0x114, 0xf18)
    elif change == 'outside-text': struct.pack_into('<i', image, 0x100c, 0x1000)
    elif change == 'unaligned': struct.pack_into('<i', image, 0x100c, -0xdff)
    elif change == 'unordered': struct.pack_into('<i', image, 0x1014, -0xe40)
    elif change == 'outside-fde': struct.pack_into('<i', image, 0x1010, 0x1800)
    elif change == 'outside-header': struct.pack_into('<i', image, 0x114, -1)
    elif change == 'missing-table': image[0x1003] = 0xff
    elif change == 'missing-count': image[0x1002] = 0xff
    elif change == 'relative-count': image[0x1002] = 0x13
    elif change == 'bss-header': struct.pack_into('<ii', image, 0x110, 0x2700, 0x271c)
    with pytest.raises(PCError, match='Switch unwind'):
        discovery.entries(image, inspection)


def test_absent_unwind_metadata_and_omitted_table_are_supported():
    image, inspection = original()
    struct.pack_into('<ii', image, 0x110, 0, 0)
    assert discovery.unwind_entries(image, inspection) == []
    image, inspection = original()
    image[0x1001:0x1004] = bytes((0xff, 0xff, 0xff))
    assert discovery.unwind_entries(image, inspection) == []


def test_absolute_relocated_table_is_rebased_once():
    image, inspection = original()
    image[0x1003] = 0  # absolute 64-bit pointers after host linking
    struct.pack_into('<i', image, 0x114, 0xf2c)
    struct.pack_into('<QQQQ', image, 0x100c, BASE + 0x200, BASE + 0x1100,
                     BASE + 0x240, BASE + 0x1108)
    assert discovery.unwind_entries(image, inspection) == [BASE + 0x200, BASE + 0x240]


def landing_pad_fixture(*, site_encoding=1, explicit_lp_start=False, dwarf64=False):
    image, inspection = original()
    cie, fde, lsda = 0x1080, 0x1100, 0x1160
    function = 0x200
    struct.pack_into('<II', image, 0x220, 0x52800580, 0xd65f03c0)  # mov w0,44; ret
    struct.pack_into('<II', image, 0x228, 0x528005a0, 0xd65f03c0)  # mov w0,45; ret

    def record(offset, body):
        prefix = struct.pack('<IQ', 0xffffffff, len(body)) if dwarf64 else struct.pack('<I', len(body))
        image[offset:offset + len(prefix) + len(body)] = prefix + body

    id_format, prefix_size = ('<Q', 12) if dwarf64 else ('<I', 4)
    width = struct.calcsize(id_format)
    # zPLR with an indirect personality, signed eight-byte PC-relative LSDA
    # pointer, and signed four-byte PC-relative function address.
    aug = b'\x9c' + bytes(8) + b'\x1c\x1b'
    record(cie, bytes(width) + b'\x01zPLR\0\x01\x7c\x1e' + bytes((len(aug),)) + aug)
    body = fde + prefix_size
    frame = struct.pack(id_format, body - cie)
    frame += struct.pack('<ii', function - (body + width), 0x40)
    frame += b'\x08' + struct.pack('<q', lsda - (body + width + 9))
    record(fde, frame)
    # Keep the other function's search-table entry but move its empty FDE
    # beyond the first record.
    struct.pack_into('<i', image, 0x1018, 0x11c0 - 0x1000)

    lp_start = function - 4 if explicit_lp_start else function
    lp = b'\x1b' + struct.pack('<i', lp_start - (lsda + 1)) if explicit_lp_start else b'\xff'
    sites = b''
    for row in ((0, 4, 0, 0), (4, 4, 0x220 - lp_start, 0), (8, 4, 0x228 - lp_start, 3)):
        start, length, pad, action = row
        fmt = {1: '<BBB', 3: '<III', 11: '<iii'}[site_encoding]
        sites += struct.pack(fmt, start, length, pad) + bytes((action,))
    table = bytes((site_encoding, len(sites))) + sites
    # There is a type table, but its entries are opaque to entry discovery.
    value = lp + bytes((0x9c, len(table))) + table
    image[lsda:lsda + len(value)] = value
    return image, inspection


@pytest.mark.parametrize('site_encoding', [1, 3, 11])
@pytest.mark.parametrize('explicit_lp_start', [False, True])
@pytest.mark.parametrize('dwarf64', [False, True])
def test_unwind_exception_pads_are_rebased_native_entries(site_encoding, explicit_lp_start, dwarf64):
    image, inspection = landing_pad_fixture(
        site_encoding=site_encoding, explicit_lp_start=explicit_lp_start, dwarf64=dwarf64)
    assert discovery.entries(image, inspection) == [BASE, BASE + 0x200, BASE + 0x220, BASE + 0x228, BASE + 0x240]


@pytest.mark.parametrize('change', ['bad-fde-size', 'bad-cie-offset', 'wrong-function',
                                    'bad-lsda-pointer', 'bad-type-table', 'truncated-call-site',
                                    'unaligned-pad', 'outside-frame'])
def test_malformed_landing_pad_metadata_fails_before_translation(change):
    image, inspection = landing_pad_fixture()
    if change == 'bad-fde-size': struct.pack_into('<I', image, 0x1100, 0x10000)
    elif change == 'bad-cie-offset': struct.pack_into('<I', image, 0x1104, 0x4000)
    elif change == 'wrong-function': struct.pack_into('<i', image, 0x1108, 0x204 - 0x1108)
    elif change == 'bad-lsda-pointer': struct.pack_into('<q', image, 0x1111, 0x2500 - 0x1111)
    elif change == 'bad-type-table': image[0x1162] = 2
    elif change == 'truncated-call-site': image[0x1164] = 11
    elif change == 'unaligned-pad': image[0x116b] += 1
    elif change == 'outside-frame': image[0x116a] = 0x7f
    with pytest.raises(PCError, match='Switch unwind'):
        discovery.entries(image, inspection)
