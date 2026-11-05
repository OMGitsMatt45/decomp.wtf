"""Address-derived roots, following Kirikae's MIT function-discovery approach.

Unwind tables and ADR / ADRP+ADD roots supplement the loader's entry point.
Candidates remain ordinary translated entries, never HLE bindings.
"""
import struct

from ..pc import PCError


def unwind_entries(image, inspection):
    """Read MOD0's bounded .eh_frame_hdr search table (DWARF pointer encodings).

    Retail modules retain function boundaries here even when dynamic symbols
    and relocated callback pointers do not identify the functions. MOD0's end
    bounds the header/search table, not the FDE records following it.
    """
    if len(image) < 8:
        return []
    mod0 = struct.unpack_from('<I', image, 4)[0]
    if not mod0 or image[mod0:mod0 + 4] != b'MOD0':
        return []
    regions = [(s['offset'], s['offset'] + s['size']) for s in inspection['segments'] if s['size']]

    def read(offset, size, end=None):
        if (offset < 0 or size < 0 or end is not None and offset + size > end
                or not any(lo <= offset and offset + size <= hi for lo, hi in regions)):
            raise PCError('Switch unwind metadata exceeds initialized segments or its declared header')
        return image[offset:offset + size]

    begin, finish = struct.unpack_from('<ii', read(mod0 + 16, 8))
    if begin == finish == 0:
        return []
    start, end = mod0 + begin, mod0 + finish
    if end <= start:
        raise PCError('invalid Switch unwind header range')
    version, pointer_encoding, count_encoding, table_encoding = read(start, 4, end)
    if version != 1:
        raise PCError('unsupported Switch unwind header version')

    formats = {0: '<Q', 2: '<H', 3: '<I', 4: '<Q', 10: '<h', 11: '<i', 12: '<q'}

    def encoded(offset, encoding):
        fmt = formats.get(encoding & 15)
        application = encoding & 0x70
        if not fmt or encoding & 0x80 or application not in (0, 0x10, 0x30):
            raise PCError('unsupported Switch unwind pointer encoding')
        size = struct.calcsize(fmt)
        value, = struct.unpack(fmt, read(offset, size, end))
        if application == 0x10:
            value += offset
        elif application == 0x30:
            value += start
        elif inspection['base'] <= value < inspection['base'] + len(image):
            value -= inspection['base']
        return value, offset + size

    at = start + 4
    if pointer_encoding != 0xff:
        pointer, at = encoded(at, pointer_encoding)
        read(pointer, 4)
    if count_encoding == 0xff:
        if table_encoding != 0xff:
            raise PCError('Switch unwind table has no entry count')
        return []
    if count_encoding & 0xf0:
        raise PCError('unsupported Switch unwind count encoding')
    count, at = encoded(at, count_encoding)
    if not 0 <= count <= 1 << 20:
        raise PCError('Switch unwind entry count exceeds its bound')
    if table_encoding == 0xff:
        if count:
            raise PCError('Switch unwind entries have no search table')
        return []
    text = inspection['segments'][0]
    lo, hi = text['offset'], text['offset'] + text['size']
    roots, previous = set(), -1
    for _ in range(count):
        function, at = encoded(at, table_encoding)
        fde, at = encoded(at, table_encoding)
        if function % 4 or not lo <= function < hi or function < previous:
            raise PCError('Switch unwind function is outside ordered executable text')
        read(fde, 4)
        roots.add(inspection['base'] + function)
        previous = function
    return sorted(roots)


def entries(image, inspection):
    base = inspection['base']
    text = inspection['segments'][0]
    lo, hi = base + text['offset'], base + text['offset'] + text['size']
    roots = {inspection['entry'], *unwind_entries(image, inspection)}
    returns_twice = inspection.get('returns_twice', {})
    return_targets = set(returns_twice.get('functions', ()))
    return_slots = set(returns_twice.get('slots', ()))

    def add(target):
        if lo <= target < hi and target % 4 == 0:
            roots.add(target)

    words = list(struct.iter_unpack('<I', image[text['offset']:text['offset'] + text['size']]))
    for i, (word,) in enumerate(words):
        pc = lo + i * 4
        kind = word & 0x9f000000
        if kind not in (0x10000000, 0x90000000):
            continue
        immediate = ((word >> 5 & 0x7ffff) << 2) | (word >> 29 & 3)
        if immediate & (1 << 20):
            immediate -= 1 << 21
        if kind == 0x10000000:
            add(pc + immediate)
        elif i + 1 < len(words):
            following = words[i + 1][0]
            page = (pc & ~0xfff) + (immediate << 12)
            # Adjacent ADD Xd, Xn, #imm, where Xn is this ADRP's destination.
            if following & 0xff800000 == 0x91000000 and following >> 5 & 31 == word & 31:
                delta = (following >> 10 & 0xfff) << (12 if following & (1 << 22) else 0)
                add(page + delta)
            # AArch64 PLT entries load an identified JUMP_SLOT and branch to it.
            if return_slots and word & 31 == 16 and following & 0xffc003ff == 0xf9400211 and i + 3 < len(words):
                offset = (following >> 10 & 0xfff) * 8
                if (offset < 0x1000 and page + offset in return_slots
                        and words[i + 2][0] == (0x91000210 | offset << 10) and words[i + 3][0] == 0xd61f0220):
                    return_targets.add(pc)

    if return_targets:
        for i, (word,) in enumerate(words):
            if word >> 26 == 0x25:  # BL imm26
                pc = lo + i * 4
                immediate = ((word & 0x3ffffff) ^ 0x2000000) - 0x2000000
                if pc + (immediate << 2) in return_targets:
                    # longjmp can re-enter immediately after the original call.
                    add(pc + 4)
    return sorted(roots)
