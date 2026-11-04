"""Address-derived roots, following Kirikae's MIT function-discovery approach.

ADR / ADRP+ADD roots supplement the loader's entry point, as in Kirikae's
loader/discovery pipeline pinned in sources.json. Candidates remain ordinary
translated entries, never HLE bindings.
"""
import struct


def entries(image, inspection):
    base = inspection['base']
    text = inspection['segments'][0]
    lo, hi = base + text['offset'], base + text['offset'] + text['size']
    roots = {inspection['entry']}

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
            # Adjacent ADD Xd, Xn, #imm, where Xn is this ADRP's destination.
            if following & 0xff800000 == 0x91000000 and following >> 5 & 31 == word & 31:
                delta = (following >> 10 & 0xfff) << (12 if following & (1 << 22) else 0)
                add((pc & ~0xfff) + (immediate << 12) + delta)
    return sorted(roots)
