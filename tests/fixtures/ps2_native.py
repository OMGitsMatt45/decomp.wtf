"""CC0 original R5900 programs and a bounded, independent byte interpreter.

This is a CPU oracle for these short programs, not a PS2 emulator. It decodes
their original instruction words without importing candidate code or macros.
Scalar EE results preserve the upper 64 bits of a 128-bit GPR; word arithmetic
sign-extends into its lower 64 bits. Packed operations use all four word lanes.
"""
from __future__ import annotations

import struct

BASE = 0x100000
DATA = 0x200000
STOP = 0x1F00000
MASK64 = (1 << 64) - 1
MASK128 = (1 << 128) - 1


def i(op, rs, rt, immediate):
    return op << 26 | rs << 21 | rt << 16 | (immediate & 0xFFFF)


def r(fn, rs=0, rt=0, rd=0, sa=0):
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn


def packed(group, operation, rd=2):
    return 0x1C << 26 | 4 << 21 | 5 << 16 | rd << 11 | operation << 6 | group


def program():
    """A symbol-bearing ELF32 built directly from original instruction words."""
    ret = [r(8, rs=31), 0]
    functions = {
        'word_add': [r(0x21, 4, 5, 2), *ret],
        'wide_add': [r(0x2D, 4, 5, 2), *ret],
        'wide_shift': [r(0x38, rt=4, rd=2, sa=7), r(0x3E, rt=5, rd=3, sa=8), *ret],
        'unsigned_compare': [r(0x2B, 4, 5, 2), *ret],
        'signed_immediate': [i(0x19, 4, 2, -17), i(0xF, 0, 3, 0x8001), *ret],
        'multiply': [r(0x18, 4, 5), r(0x12, rd=2), r(0x10, rd=3), *ret],
        'memory': [i(0x2B, 6, 4, 0), i(0x23, 6, 2, 0), i(0x27, 6, 3, 0),
                   i(0x3F, 6, 5, 8), i(0x37, 6, 8, 8), i(0x20, 6, 9, 0),
                   i(0x24, 6, 10, 0), i(0x21, 6, 11, 2), i(0x25, 6, 12, 2),
                   i(0x1F, 6, 4, 16), i(0x1E, 6, 13, 16), i(0x1F, 6, 13, 32), *ret],
        'packed_add': [packed(8, 0), *ret],
        'packed_saturate': [packed(8, 0x10), *ret],
        'packed_extract_low': [packed(8, 0x12), *ret],
        'packed_extract_high': [packed(0x28, 0x12), *ret],
        'packed_and': [packed(9, 0x12), *ret],
        'zero_register': [r(0x2D, 4, 5, 0), packed(8, 0, rd=0), r(0x2D, 0, 4, 2), *ret],
        'branch_delay': [i(9, 0, 2, 1), i(4, 4, 5, 2), i(9, 4, 4, 1),
                         i(9, 2, 2, 8), r(8, rs=31), i(9, 2, 2, 2)],
        'branch_likely': [i(9, 0, 2, 1), i(0x14, 4, 5, 2), i(9, 2, 2, 4),
                          i(9, 2, 2, 8), *ret],
        'branch_not_likely': [i(9, 0, 2, 1), i(0x15, 4, 5, 2), i(9, 2, 2, 4),
                              i(9, 2, 2, 8), *ret],
        'direct_call': [],
        'indirect_call': [r(0x25, 31, 0, 8), r(9, rs=25, rd=31), r(0x25, 0, 0, 25),
                          r(0x25, 8, 0, 31), *ret],
        'helper': [r(0x2D, 4, 5, 2), r(8, rs=31), i(0x19, 2, 2, 1)],
    }
    entries = {name: BASE + index * 0x100 for index, name in enumerate(functions)}
    functions['direct_call'] = [i(9, 29, 29, -16), i(0x3F, 29, 31, 0),
        3 << 26 | entries['helper'] >> 2, i(9, 4, 4, 1), i(0x37, 29, 31, 0),
        r(8, rs=31), i(9, 29, 29, 16)]
    code = bytearray(len(functions) * 0x100)
    for name, words in functions.items():
        struct.pack_into('<' + 'I' * len(words), code, entries[name] - BASE, *words)

    # ELF sections: null, .text, .shstrtab, .strtab, .symtab. One PT_LOAD.
    strings = bytearray(b'\0')
    symbols = bytearray(16)
    for name, words in functions.items():
        offset = len(strings)
        strings.extend(('probe_' + name).encode() + b'\0')
        symbols.extend(struct.pack('<IIIBBH', offset, entries[name], len(words) * 4, 0x12, 0, 1))
    names = b'\0.text\0.shstrtab\0.strtab\0.symtab\0'
    image = bytearray(0x100) + code
    name_off = len(image); image.extend(names)
    string_off = len(image); image.extend(strings)
    image.extend(b'\0' * (-len(image) % 4))
    symbol_off = len(image); image.extend(symbols)
    section_off = len(image)
    image.extend(bytes(40))
    image.extend(struct.pack('<10I', 1, 1, 6, BASE, 0x100, len(code), 0, 0, 16, 0))
    image.extend(struct.pack('<10I', 7, 3, 0, 0, name_off, len(names), 0, 0, 1, 0))
    image.extend(struct.pack('<10I', 17, 3, 0, 0, string_off, len(strings), 0, 0, 1, 0))
    image.extend(struct.pack('<10I', 25, 2, 0, 0, symbol_off, len(symbols), 3, 1, 4, 16))
    struct.pack_into('<16sHHIIIIIHHHHHH', image, 0, b'\x7fELF\x01\x01\x01' + bytes(9),
        2, 8, 1, BASE, 52, section_off, 0x20924001, 52, 32, 1, 40, 5, 2)
    struct.pack_into('<8I', image, 52, 1, 0x100, BASE, BASE, len(code), len(code), 7, 16)
    return bytes(image), bytes(code), entries


def cases():
    _, _, entries = program()
    vectors = [(0, 0), (0xFFFFFFFF80000000, 0x7FFFFFFF),
               (0x800000007FFFFFFF00000001FFFFFFFF, 0x7FFFFFFF800000000000000200000001)]
    return [(name, a, b) for name in entries if name != 'helper' for a, b in vectors]


def initial(a, b, entries):
    regs = [(0xA500000000000000 + n) << 64 | (0x51000000 + n) for n in range(32)]
    regs[0] = 0
    regs[4], regs[5], regs[6] = a, b, DATA
    regs[25], regs[29], regs[31] = entries['helper'], 0x1FFF000, STOP
    return regs


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def reference(code, entry, a, b, entries):
    regs = initial(a, b, entries)
    memory = bytearray(32 * 1024 * 1024)
    memory[BASE:BASE + len(code)] = code
    memory[DATA:DATA + 64] = bytes(range(64))
    hi, lo = 0x12345678, 0xABCDEF01
    pc, pending = entry, None

    def scalar(reg, value):
        if reg:
            regs[reg] = regs[reg] & (MASK128 ^ MASK64) | value & MASK64

    for _ in range(256):
        if pc == STOP:
            return dict(registers=[f'{v:032x}' for v in regs], hi=hi, lo=lo,
                        memory=memory[DATA:DATA + 64].hex(), pc=pc)
        if not BASE <= pc < BASE + len(code) or pc & 3:
            raise ValueError(f'oracle jumped outside original code: {pc:#x}')
        word = int.from_bytes(memory[pc:pc + 4], 'little')
        op, rs, rt, rd, sa, fn = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word >> 6 & 31, word & 63
        imm = signed(word, 16)
        x, y = regs[rs] & MASK64, regs[rt] & MASK64
        following, branch = pc + 4, None
        if op == 0:
            if fn in (8, 9):
                branch = x & 0xFFFFFFFF
                if fn == 9: scalar(rd, pc + 8)
            elif fn == 0: scalar(rd, signed((y & 0xFFFFFFFF) << sa, 32))
            elif fn == 0x21: scalar(rd, signed(x + y, 32))
            elif fn == 0x2D: scalar(rd, x + y)
            elif fn == 0x25: scalar(rd, x | y)
            elif fn == 0x2B: scalar(rd, int(x < y))
            elif fn == 0x38: scalar(rd, y << sa)
            elif fn == 0x3E: scalar(rd, y >> (sa + 32))
            elif fn == 0x18:
                product = signed(x, 32) * signed(y, 32)
                lo, hi = signed(product, 32) & MASK64, signed(product >> 32, 32) & MASK64
                scalar(rd, lo)
            elif fn == 0x12: scalar(rd, lo)
            elif fn == 0x10: scalar(rd, hi)
            else: raise ValueError(f'oracle SPECIAL {word:#x}')
        elif op == 3:
            scalar(31, pc + 8); branch = (pc + 4) & 0xF0000000 | (word & 0x3FFFFFF) << 2
        elif op in (4, 0x14, 0x15):
            take = x == y if op != 0x15 else x != y
            if take: branch = pc + 4 + 4 * imm
            elif op in (0x14, 0x15): following += 4
        elif op == 9: scalar(rt, signed(x + imm, 32))
        elif op == 0x19: scalar(rt, x + imm)
        elif op == 0xF: scalar(rt, signed((word & 0xFFFF) << 16, 32))
        elif op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x27, 0x37, 0x1E):
            size = {0x20: 1, 0x21: 2, 0x23: 4, 0x24: 1, 0x25: 2, 0x27: 4, 0x37: 8, 0x1E: 16}[op]
            addr = (x + imm) & 0x1FFFFFFF
            value = int.from_bytes(memory[addr:addr + size], 'little', signed=op in (0x20, 0x21, 0x23))
            if op == 0x1E:
                if rt: regs[rt] = value
            else: scalar(rt, value)
        elif op in (0x2B, 0x3F, 0x1F):
            size = {0x2B: 4, 0x3F: 8, 0x1F: 16}[op]
            addr = (x + imm) & 0x1FFFFFFF
            memory[addr:addr + size] = (regs[rt] & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')
        elif op == 0x1C:
            left = [(regs[rs] >> shift) & 0xFFFFFFFF for shift in range(0, 128, 32)]
            right = [(regs[rt] >> shift) & 0xFFFFFFFF for shift in range(0, 128, 32)]
            if fn == 8 and sa == 0: out = [(l + v) & 0xFFFFFFFF for l, v in zip(left, right)]
            elif fn == 8 and sa == 0x10:
                out = [max(-0x80000000, min(0x7FFFFFFF, signed(l, 32) + signed(v, 32))) & 0xFFFFFFFF for l, v in zip(left, right)]
            elif fn in (8, 0x28) and sa == 0x12:
                n = 0 if fn == 8 else 2; out = [right[n], left[n], right[n + 1], left[n + 1]]
            elif fn == 9 and sa == 0x12: out = [l & v for l, v in zip(left, right)]
            else: raise ValueError(f'oracle MMI {word:#x}')
            if rd: regs[rd] = sum(v << (32 * n) for n, v in enumerate(out))
        else: raise ValueError(f'oracle opcode {word:#x}')
        if pending is not None:
            if branch is not None: raise ValueError('branch in oracle delay slot')
            following = pending
        pc, pending = following, branch
    raise ValueError('original fixture exceeded the instruction bound')
