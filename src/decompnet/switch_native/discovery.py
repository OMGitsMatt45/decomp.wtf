"""Address-derived roots, following Kirikae's MIT function-discovery approach.

Unwind tables and ADR / ADRP+ADD roots supplement the loader's entry point.
Candidates remain ordinary translated entries, never HLE bindings.
"""
import struct

from ..pc import PCError


_UNWIND_FORMATS = {0: '<Q', 2: '<H', 3: '<I', 4: '<Q', 8: '<q', 10: '<h', 11: '<i', 12: '<q'}


def _unwind_scalar(read, offset, encoding, end):
    fmt = _UNWIND_FORMATS.get(encoding & 15)
    if fmt:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, read(offset, size, end))[0], offset + size
    kind = encoding & 15
    if kind not in (1, 9):
        raise PCError('unsupported Switch unwind pointer encoding')
    value = 0
    for shift in range(0, 70, 7):
        byte, = read(offset, 1, end)
        offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            if kind == 9 and byte & 0x40:
                value -= 1 << (shift + 7)
            minimum, maximum = (-(1 << 63), 1 << 63) if kind == 9 else (0, 1 << 64)
            if minimum <= value < maximum:
                return value, offset
            break
    raise PCError('Switch unwind LEB128 value exceeds its bound')


def _unwind_pointer(read, offset, encoding, end, base, *, data=None, function=None, nullable=False):
    application = encoding & 0x70
    relative = {0x10: offset, 0x30: data, 0x40: function}
    if encoding & 0x80 or (application and relative.get(application) is None):
        raise PCError('unsupported Switch unwind pointer encoding')
    value, following = _unwind_scalar(read, offset, encoding, end)
    if nullable and not value:
        return None, following
    if application:
        value += relative[application]
    elif value >= base:
        value -= base
    return value, following


def _unwind_record(read, offset):
    size, = struct.unpack('<I', read(offset, 4))
    offset += 4
    width = 4
    if size == 0xffffffff:
        size, = struct.unpack('<Q', read(offset, 8))
        offset += 8
        width = 8
    if size and size < width:
        raise PCError('invalid Switch unwind record length')
    read(offset, size)
    return offset, offset + size, width


def _cie_encodings(read, offset):
    at, end, width = _unwind_record(read, offset)
    if at == end or any(read(at, width, end)):
        raise PCError('invalid Switch unwind common information entry')
    version, = read(at + width, 1, end)
    at += width + 1
    if version not in (1, 3, 4) or read(at, 1, end) != b'z':
        return None
    augmentation = bytearray()
    while (character := read(at, 1, end)) != b'\0':
        augmentation.extend(character)
        at += 1
    at += 1
    if b'L' not in augmentation or any(char not in b'zPLRS' for char in augmentation):
        return None
    if version == 4:
        if read(at, 2, end) != b'\x08\0':
            return None
        at += 2
    for kind in (1, 9):
        _, at = _unwind_scalar(read, at, kind, end)
    if version == 1:
        read(at, 1, end)
        at += 1
    else:
        _, at = _unwind_scalar(read, at, 1, end)
    size, at = _unwind_scalar(read, at, 1, end)
    read(at, size, end)
    end = at + size
    lsda_encoding, fde_encoding = 0xff, 0
    for char in augmentation[1:]:
        if char in b'PLR':
            encoding, = read(at, 1, end)
            at += 1
            if char == ord('P'):
                # The personality address is opaque here, including indirect
                # encodings. Consume its bytes without dereferencing it.
                _, at = _unwind_scalar(read, at, encoding, end)
            elif char == ord('L'):
                lsda_encoding = encoding
            else:
                fde_encoding = encoding
    return (lsda_encoding, fde_encoding) if lsda_encoding != 0xff else None


def _lsda_entries(read, at, end, function, function_end, base, text):
    lp_encoding, = read(at, 1, end)
    at += 1
    lp_start = function
    if lp_encoding != 0xff:
        lp_start, at = _unwind_pointer(read, at, lp_encoding, end, base, function=function)
    type_encoding, = read(at, 1, end)
    at += 1
    if type_encoding != 0xff:
        # The type table is unnecessary for locating landing pads. Its
        # declared base still bounds the preceding call-site table.
        type_offset, at = _unwind_scalar(read, at, 1, end)
        read(at, type_offset, end)
        end = at + type_offset
    site_encoding, = read(at, 1, end)
    if site_encoding & 0xf0:
        raise PCError('unsupported Switch unwind call-site encoding')
    size, at = _unwind_scalar(read, at + 1, 1, end)
    read(at, size, end)
    end = at + size
    while at < end:
        start, at = _unwind_scalar(read, at, site_encoding, end)
        length, at = _unwind_scalar(read, at, site_encoding, end)
        pad, at = _unwind_scalar(read, at, site_encoding, end)
        _, at = _unwind_scalar(read, at, 1, end)  # action, including cleanup-only zero
        if start < 0 or length < 0 or function + start + length > function_end:
            raise PCError('Switch unwind call site exceeds its frame range')
        if pad:
            target = lp_start + pad
            if pad < 0 or target % 4 or not text[0] <= target < text[1]:
                raise PCError('Switch unwind landing pad is outside aligned executable text')
            yield target


def _landing_pads(read, fde, function, base, text, regions, cies):
    at, end, width = _unwind_record(read, fde)
    if at == end:
        return  # Preserve search-table-only metadata without an FDE body.
    cie = at - int.from_bytes(read(at, width, end), 'little')
    if cie >= fde:
        raise PCError('invalid Switch unwind common information reference')
    if cie not in cies:
        cies[cie] = _cie_encodings(read, cie)
    encodings = cies[cie]
    if encodings is None:
        return
    lsda_encoding, fde_encoding = encodings
    start, at = _unwind_pointer(read, at + width, fde_encoding, end, base)
    length, at = _unwind_scalar(read, at, fde_encoding & 15, end)
    if start != function or not 0 < length <= text[1] - start:
        raise PCError('invalid Switch unwind frame range')
    size, at = _unwind_scalar(read, at, 1, end)
    read(at, size, end)
    if not size:
        return
    lsda, _ = _unwind_pointer(read, at, lsda_encoding, at + size, base, function=start, nullable=True)
    if lsda is None:
        return
    lsda_end = next((hi for lo, hi in regions if lo <= lsda < hi), None)
    if lsda_end is None:
        raise PCError('Switch unwind LSDA is outside initialized segments')
    yield from _lsda_entries(read, lsda, lsda_end, start, start + length, base, text)


def unwind_entries(image, inspection):
    """Find function starts and exception landing pads through MOD0 unwind metadata.

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
        if (offset < 0 or size < 0 or offset + size > len(image) or end is not None and offset + size > end
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

    base = inspection['base']

    def encoded(offset, encoding):
        return _unwind_pointer(read, offset, encoding, end, base, data=start)

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
    roots, cies, previous = set(), {}, -1
    for _ in range(count):
        function, at = encoded(at, table_encoding)
        fde, at = encoded(at, table_encoding)
        if function % 4 or not lo <= function < hi or function < previous:
            raise PCError('Switch unwind function is outside ordered executable text')
        roots.add(base + function)
        roots.update(base + pad for pad in _landing_pads(read, fde, function, base, (lo, hi), regions, cies))
        previous = function
    return sorted(roots)


def entries(image, inspection, *, anchor_origins=None):
    base = inspection['base']
    text = inspection['segments'][0]
    lo, hi = base + text['offset'], base + text['offset'] + text['size']
    hard_roots = {inspection['entry'], *unwind_entries(image, inspection)}
    roots = set(hard_roots)
    returns_twice = inspection.get('returns_twice', {})
    return_targets = set(returns_twice.get('functions', ()))
    return_slots = set(returns_twice.get('slots', ()))

    def add(target, origin=None):
        if lo <= target < hi and target % 4 == 0:
            roots.add(target)
            if anchor_origins is not None:
                if origin is None:
                    hard_roots.add(target)
                elif (target not in hard_roots and target > lo
                      and words[(target - lo) // 4 - 1][0] & 0xfffffc1f == 0xd61f0000):
                    anchor_origins.setdefault(target, []).append(origin)

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
            add(pc + immediate, pc)
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
    if anchor_origins is not None:
        # The emitter must account for every ADR to a candidate anchor.
        # Entry, unwind, ADRP+ADD and returns-twice roots stay independent.
        for target in hard_roots:
            anchor_origins.pop(target, None)
    return sorted(roots)
