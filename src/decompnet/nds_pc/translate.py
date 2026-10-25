"""Bounded ARMv4T/v5TE to C++ translation. Unsupported instructions stop export.

Instructions are decoded here, at generation time. Generated code contains no
instruction decoder, interpreter or runtime compiler.
"""
from dataclasses import dataclass


class TranslationError(ValueError):
    pass


@dataclass(frozen=True)
class Instruction:
    address: int
    size: int
    thumb: bool
    body: str


def u(value):
    return f'0x{value & 0xffffffff:08x}u'


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def reg(n, address, thumb=False):
    return u(address + (4 if thumb else 8)) if n == 15 else f'c.r[{n}]'


def branch(value, exchange=False):
    return f'rt.branch(c, {value}, {str(exchange).lower()});'


def put(n, value, flags=False):
    if n == 15:
        if flags:
            raise TranslationError('CPSR restore through PC is not implemented')
        return branch(value)
    return f'c.r[{n}] = {value};'


def alu(op, a, b, dest, flags, carry='c.carry'):
    """Emit operations, not a runtime opcode switch."""
    tests = op in (8, 9, 10, 11)
    if tests:
        flags = True
    if dest == 15 and flags and not tests:
        raise TranslationError('banked status restore is not implemented')
    arith = {2: (a, f'~({b})', 'true'), 3: (b, f'~({a})', 'true'),
             4: (a, b, 'false'), 5: (a, b, 'c.carry'),
             6: (a, f'~({b})', 'c.carry'), 7: (b, f'~({a})', 'c.carry'),
             10: (a, f'~({b})', 'true'), 11: (a, b, 'false')}
    if op in arith:
        x, y, cin = arith[op]
        code = f'auto value = add(c, {x}, {y}, {cin}, {str(flags).lower()});'
    else:
        expression = {0: f'{a} & {b}', 1: f'{a} ^ {b}', 8: f'{a} & {b}',
                      9: f'{a} ^ {b}', 12: f'{a} | {b}', 13: b,
                      14: f'{a} & ~({b})', 15: f'~({b})'}[op]
        code = f'auto value = uint32_t({expression});'
        if flags:
            code += f' logic_flags(c, value, {carry});'
    if not tests:
        code += ' ' + put(dest, 'value', flags)
    return code


def multiple(load, base, mask, pre, up, writeback, cpu):
    registers = [r for r in range(16) if mask & (1 << r)]
    if not registers or base == 15 or writeback and base in registers:
        raise TranslationError('empty or overlapping block-transfer register list')
    count = len(registers)
    start = (4 if pre else 0) if up else -4 * count + (0 if pre else 4)
    code = f'auto base = c.r[{base}]; auto address = base + {u(start)};'
    # Snapshot store operands before any writes or writeback.
    if not load and 15 in registers:
        raise TranslationError('store-PC block transfers are not implemented')
    for i, n in enumerate(registers):
        addr = f'address + {4*i}u'
        if load:
            value = f'rt.read32({addr})'
            code += branch(value, cpu == 'arm9') if n == 15 else f' c.r[{n}] = {value};'
        else:
            code += f' rt.write32({addr}, c.r[{n}]);'
    if writeback:
        code += f' c.r[{base}] = base + {u(4*count if up else -4*count)};'
    return code


def arm(word, address, cpu):
    cond = word >> 28
    if cond == 15:
        if word & 0xfe000000 == 0xfa000000 and cpu == 'arm9':
            target = address + 8 + signed(((word & 0xffffff) << 2) | ((word >> 23) & 2), 26)
            return f'c.r[14] = {u(address+4)}; ' + branch(u(target | 1), True)
        raise TranslationError('unconditional extension is not implemented for this CPU')
    a, b, d = (word >> 16) & 15, word & 15, (word >> 12) & 15
    if word & 0x0ffffff0 in (0x012fff10, 0x012fff30):
        link = word & 0x20
        if link and cpu != 'arm9':
            raise TranslationError('ARM7 does not support BLX')
        code = f'auto target = {reg(b,address)}; '
        if link:
            code += f'c.r[14] = {u(address+4)}; '
        code += branch('target', True)
    elif word & 0x0e000000 == 0x0a000000:
        code = f'c.r[14] = {u(address+4)}; ' if word & (1 << 24) else ''
        code += branch(u(address + 8 + signed((word & 0xffffff) << 2, 26)))
    elif word & 0x0e000000 == 0x08000000:
        if word & (1 << 22):
            raise TranslationError('user/banked register transfer is not implemented')
        code = multiple(bool(word & (1 << 20)), a, word & 0xffff, bool(word & (1 << 24)),
                        bool(word & (1 << 23)), bool(word & (1 << 21)), cpu)
    elif word & 0x0c000000 == 0x04000000:
        pre, up, byte, wb, load = [bool(word & (1 << bit)) for bit in (24, 23, 22, 21, 20)]
        if not pre and wb or a == 15 and (not pre or wb) or load and a == d and (wb or not pre):
            raise TranslationError('unprivileged or overlapping transfer writeback is not implemented')
        if word & (1 << 25):
            if word & 0x10:
                raise TranslationError('invalid register-offset transfer')
            offset = f'shift({reg(b,address)}, {(word >> 5)&3}, {(word >> 7)&31}u, c.carry, false).value'
        else:
            offset = u(word & 0xfff)
        code = f'auto base = {reg(a,address)}; auto offset = {offset}; auto updated = base {"+" if up else "-"} offset; '
        addr = 'updated' if pre else 'base'
        width = 8 if byte else 32
        if load:
            code += branch(f'rt.read{width}({addr})', cpu == 'arm9') if d == 15 else f'c.r[{d}] = rt.read{width}({addr});'
        else:
            if d == 15:
                raise TranslationError('store-PC is not implemented')
            code += f'rt.write{width}({addr}, c.r[{d}]);'
        if wb or not pre:
            code += f' c.r[{a}] = updated;'
    elif word & 0x0fc000f0 == 0x00000090:
        if word & (1 << 21) or d != 0 or 15 in (a, b, (word >> 8) & 15):
            raise TranslationError('multiply-accumulate or multiply-PC is not implemented')
        code = f'c.r[{a}] = c.r[{b}] * c.r[{(word >> 8)&15}];'
        if word & (1 << 20):
            code += f' logic_flags(c, c.r[{a}], c.carry);'
    elif word & 0x0c000000 == 0:
        op, flags = (word >> 21) & 15, bool(word & (1 << 20))
        if op in (8, 9, 10, 11) and not flags:
            raise TranslationError('status-register or extension instruction is not implemented')
        if word & (1 << 25):
            amount, imm = ((word >> 8) & 15) * 2, word & 255
            value = ((imm >> amount) | (imm << (32-amount))) & 0xffffffff if amount else imm
            shifted = f'Shift{{{u(value)}, {str(bool(value & 0x80000000)).lower() if amount else "c.carry"}}}'
        else:
            register = bool(word & 0x10)
            if register and word & 0x80 or register and (b == 15 or (word >> 8) & 15 == 15):
                raise TranslationError('extension or PC register-shift operand is not implemented')
            amount = f'(c.r[{(word >> 8)&15}] & 255u)' if register else f'{(word >> 7)&31}u'
            shifted = f'shift({reg(b,address)}, {(word >> 5)&3}, {amount}, c.carry, {str(register).lower()})'
        code = f'auto operand = {shifted}; ' + alu(op, reg(a,address), 'operand.value', d, flags, 'operand.carry')
    else:
        raise TranslationError('coprocessor, exception or unsupported ARM instruction')
    return f'if (condition(c, {cond})) {{ {code} }}'


def thumb(half, tail, address, cpu):
    d, n, m = half & 7, (half >> 3) & 7, (half >> 6) & 7
    if half & 0xf800 == 0xf000:
        if tail is None or tail & 0xf800 not in (0xf800, 0xe800):
            raise TranslationError('incomplete Thumb long branch')
        exchange = tail & 0xf800 == 0xe800
        if exchange and tail & 1:
            raise TranslationError('invalid Thumb BLX alignment encoding')
        if exchange and cpu != 'arm9':
            raise TranslationError('ARM7 does not support BLX')
        target = address + 4 + signed(((half & 0x7ff) << 12) | ((tail & 0x7ff) << 1), 23)
        value = (target & ~3) if exchange else target | 1
        return 4, f'c.r[14] = {u((address+4)|1)}; ' + branch(u(value), True)
    if half & 0xf800 < 0x1800:
        op = (half >> 11) & 3
        code = f'auto operand = shift(c.r[{n}], {op}, {(half>>6)&31}u, c.carry, false); c.r[{d}] = operand.value; logic_flags(c, operand.value, operand.carry);'
    elif half & 0xf800 == 0x1800:
        operand = u(m) if half & 0x400 else f'c.r[{m}]'
        code = alu(2 if half & 0x200 else 4, f'c.r[{n}]', operand, d, True)
    elif half & 0xe000 == 0x2000:
        op, d = (half >> 11) & 3, (half >> 8) & 7
        code = alu((13, 10, 4, 2)[op], f'c.r[{d}]', u(half & 255), d, True)
    elif half & 0xfc00 == 0x4000:
        op = (half >> 6) & 15
        if op in (2, 3, 4, 7):
            code = f'auto operand = shift(c.r[{d}], {(0,1,2,3)[(2,3,4,7).index(op)]}, c.r[{n}] & 255u, c.carry, true); c.r[{d}] = operand.value; logic_flags(c, operand.value, operand.carry);'
        elif op == 13:
            code = f'c.r[{d}] *= c.r[{n}]; logic_flags(c, c.r[{d}], c.carry);'
        elif op == 9:
            code = alu(2, '0u', f'c.r[{n}]', d, True)
        else:
            code = alu({0:0,1:1,5:5,6:6,8:8,10:10,11:11,12:12,14:14,15:15}[op], f'c.r[{d}]', f'c.r[{n}]', d, True)
    elif half & 0xfc00 == 0x4400:
        op, d, n = (half >> 8) & 3, (half & 7) | ((half >> 4) & 8), (half >> 3) & 15
        if op == 3:
            if half & 7:
                raise TranslationError('invalid branch/exchange encoding')
            link = bool(half & 0x80)
            if link and cpu != 'arm9':
                raise TranslationError('ARM7 does not support BLX')
            code = f'auto target = {reg(n,address,True)}; ' + (f'c.r[14] = {u((address+2)|1)}; ' if link else '') + branch('target', True)
        else:
            code = alu((4,10,13)[op], reg(d,address,True), reg(n,address,True), d, op == 1)
    elif half & 0xf800 == 0x4800:
        code = f'c.r[{(half>>8)&7}] = rt.read32({u(((address+4)&~3)+(half&255)*4)});'
    elif half & 0xf000 == 0x5000:
        op = (half >> 9) & 7
        addr = f'c.r[{n}] + c.r[{m}]'
        if op < 3:
            code = f'rt.write{(32,16,8)[op]}({addr}, c.r[{d}]);'
        else:
            width = {3:8,4:32,5:16,6:8,7:16}[op]
            value = f'rt.read{width}({addr})'
            if op in (3,7):
                value = f'sign_extend({value}, {width})'
            code = f'c.r[{d}] = {value};'
    elif half & 0xe000 == 0x6000 or half & 0xf000 == 0x8000:
        load = bool(half & 0x800)
        width = 16 if half & 0xf000 == 0x8000 else 8 if half & 0x1000 else 32
        addr = f'c.r[{n}] + {((half>>6)&31)*(width//8)}u'
        code = f'c.r[{d}] = rt.read{width}({addr});' if load else f'rt.write{width}({addr}, c.r[{d}]);'
    elif half & 0xf000 == 0x9000:
        addr, d = f'c.r[13] + {(half&255)*4}u', (half >> 8) & 7
        code = f'c.r[{d}] = rt.read32({addr});' if half & 0x800 else f'rt.write32({addr}, c.r[{d}]);'
    elif half & 0xf000 == 0xa000:
        base = 'c.r[13]' if half & 0x800 else u((address+4)&~3)
        code = f'c.r[{(half>>8)&7}] = {base} + {(half&255)*4}u;'
    elif half & 0xff00 == 0xb000:
        code = f'c.r[13] {"-=" if half & 0x80 else "+="} {(half&127)*4}u;'
    elif half & 0xf600 == 0xb400:
        load = bool(half & 0x800)
        mask = half & 255
        if half & 0x100:
            mask |= 1 << (15 if load else 14)
        code = multiple(load, 13, mask, not load, load, True, cpu)
    elif half & 0xf000 == 0xc000:
        code = multiple(bool(half & 0x800), (half >> 8)&7, half&255, False, True, True, cpu)
    elif half & 0xf000 == 0xd000:
        cond = (half >> 8) & 15
        if cond >= 14:
            raise TranslationError('Thumb exception/undefined instruction is not implemented')
        code = f'if (condition(c, {cond})) {{ {branch(u(address+4+signed((half&255)<<1,9)))} }}'
    elif half & 0xf800 == 0xe000:
        code = branch(u(address+4+signed((half&0x7ff)<<1,12)))
    else:
        raise TranslationError('unsupported Thumb instruction')
    return 2, code


def translate(code: bytes, address: int, mode: str, cpu: str) -> list[Instruction]:
    if mode not in ('arm','thumb') or cpu not in ('arm9','arm7'):
        raise TranslationError('identify ARM/Thumb mode and ARM9/ARM7 processor')
    alignment = 2 if mode == 'thumb' else 4
    if not code or address % alignment or len(code) % alignment:
        raise TranslationError('unaligned or empty code range')
    result, at = [], 0
    while at < len(code):
        current = address + at
        try:
            if mode == 'thumb':
                half = int.from_bytes(code[at:at+2], 'little')
                tail = int.from_bytes(code[at+2:at+4], 'little') if at+4 <= len(code) else None
                size, body = thumb(half, tail, current, cpu)
            else:
                size, body = 4, arm(int.from_bytes(code[at:at+4], 'little'), current, cpu)
        except (TranslationError, KeyError) as error:
            raise TranslationError(f'{cpu} {mode} at 0x{current:08X}: {error}') from error
        result.append(Instruction(current, size, mode == 'thumb', body))
        at += size
    return result
