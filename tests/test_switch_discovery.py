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
