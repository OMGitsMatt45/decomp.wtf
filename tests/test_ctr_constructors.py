import struct

from decompnet.ctr_native.constructors import entries


def test_relative_constructor_entries_require_bounded_table_and_code_targets():
    text = bytearray(96)
    struct.pack_into('<13H', text, 0, 0xb570, 0x4c06, 0x447c, 0x4d06, 0x447d,
                     0xe003, 0x6820, 0x1900, 0x4780, 0x1d24, 0x42ac, 0xd1f9, 0xbd70)
    base = 0x100000
    table = base + 0x1000
    struct.pack_into('<II', text, 28, table - (base + 8), table + 8 - (base + 12))
    segments = [dict(address=base, size=len(text), code_offset=0),
                dict(address=table, size=8, code_offset=len(text))]
    records = struct.pack('<ii', base + 0x30 - table, base + 0x41 - (table + 4))
    assert entries(text + records, segments) == {base + 0x30, base + 0x41}
    assert not entries(text + records[:-4] + bytes(4), segments)
    assert not entries(text + records, [segments[0], {**segments[1], 'size': 4}])
