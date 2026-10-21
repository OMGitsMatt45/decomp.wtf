"""SM83 instructions in RGBDS syntax, using the Game Boy's instruction set.

Undocumented lock-up opcodes, truncated operands and STOP's nonzero padding are
preserved as DB, so a listing never silently changes their encoding.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instruction:
    address: int
    data: bytes
    text: str
    flow: str = "next"  # next | jump | branch | call | return | indirect | invalid
    target: int | None = None
    write: int | None = None  # known absolute memory write, for bank-switch boundaries


_R = ("b", "c", "d", "e", "h", "l", "[hl]", "a")
_RP = ("bc", "de", "hl", "sp")
_RP2 = ("bc", "de", "hl", "af")
_CC = ("nz", "z", "nc", "c")
_ALU = ("add a, ", "adc a, ", "sub ", "sbc a, ", "and ", "xor ", "or ", "cp ")


def decode(data: bytes, address: int = 0) -> Instruction:
    """Decode the first instruction; `address` is its 16-bit CPU PC, not a file offset."""
    if not data:
        raise ValueError("no SM83 instruction bytes")
    op = data[0]
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    size, text, flow, target, write = 1, "", "next", None, None
    n8 = data[1] if len(data) > 1 else 0
    n16 = int.from_bytes(data[1:3], "little")
    signed = n8 - 256 if n8 & 128 else n8
    imm8, imm16 = f"${n8:02x}", f"${n16:04x}"

    if x == 0:
        if z == 0:
            if y == 0:
                text = "nop"
            elif y == 1:
                text, size, write = f"ld [{imm16}], sp", 3, n16
            elif y == 2:
                size = 2
                text = "stop" if n8 == 0 else f"db $10, {imm8}"
                if n8:
                    flow = "invalid"
            else:
                target = (address + 2 + signed) & 0xFFFF
                text, size = f"jr {'' if y == 3 else _CC[y - 4] + ', '}${target:04x}", 2
                flow = "jump" if y == 3 else "branch"
        elif z == 1:
            text = f"add hl, {_RP[p]}" if q else f"ld {_RP[p]}, {imm16}"
            size = 1 if q else 3
        elif z == 2:
            ref = ("[bc]", "[de]", "[hl+]", "[hl-]")[p]
            text = f"ld a, {ref}" if q else f"ld {ref}, a"
        elif z == 3:
            text = f"{'dec' if q else 'inc'} {_RP[p]}"
        elif z in (4, 5):
            text = f"{'inc' if z == 4 else 'dec'} {_R[y]}"
        elif z == 6:
            text, size = f"ld {_R[y]}, {imm8}", 2
        else:
            text = ("rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf")[y]
    elif x == 1:
        text = "halt" if op == 0x76 else f"ld {_R[y]}, {_R[z]}"
    elif x == 2:
        text = _ALU[y] + _R[z]
    elif z == 0:
        if y < 4:
            text, flow = f"ret {_CC[y]}", "branch"  # conditional return also falls through
        elif y in (4, 6):
            ref = f"[${0xFF00 + n8:04x}]"
            text, size = (f"ldh {ref}, a" if y == 4 else f"ldh a, {ref}"), 2
        elif y == 5:
            text, size = f"add sp, {signed}", 2
        else:
            text, size = f"ld hl, sp{'+' if signed >= 0 else ''}{signed}", 2
    elif z == 1:
        if not q:
            text = f"pop {_RP2[p]}"
        else:
            text = ("ret", "reti", "jp hl", "ld sp, hl")[p]
            flow = "return" if p < 2 else "indirect" if p == 2 else "next"
    elif z == 2:
        if y < 4:
            text, size, flow, target = f"jp {_CC[y]}, {imm16}", 3, "branch", n16
        elif y in (4, 6):
            text = "ldh [$ff00+c], a" if y == 4 else "ldh a, [$ff00+c]"
        else:
            text, size = (f"ld [{imm16}], a" if y == 5 else f"ld a, [{imm16}]"), 3
            if y == 5:
                write = n16
    elif z == 3:
        if y == 0:
            text, size, flow, target = f"jp {imm16}", 3, "jump", n16
        elif y == 1:
            cx, cy, cz = n8 >> 6, (n8 >> 3) & 7, n8 & 7
            text = (f"{('rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'swap', 'srl')[cy]} {_R[cz]}"
                    if cx == 0 else f"{('bit', 'res', 'set')[cx - 1]} {cy}, {_R[cz]}")
            size = 2
        elif y in (6, 7):
            text = "di" if y == 6 else "ei"
    elif z == 4:
        if y < 4:
            text, size, flow, target = f"call {_CC[y]}, {imm16}", 3, "call", n16
    elif z == 5:
        if not q:
            text = f"push {_RP2[p]}"
        elif p == 0:
            text, size, flow, target = f"call {imm16}", 3, "call", n16
    elif z == 6:
        text, size = _ALU[y] + imm8, 2
    else:
        text, flow, target = f"rst ${y * 8:02x}", "call", y * 8

    if len(data) < size:
        size, text = len(data), ""
    if not text:
        text, flow, target, write = "db " + ", ".join(f"${v:02x}" for v in data[:size]), "invalid", None, None
    return Instruction(address, bytes(data[:size]), text, flow, target, write)


def disassemble(data: bytes, address: int = 0) -> list[Instruction]:
    out, offset = [], 0
    while offset < len(data):
        insn = decode(data[offset:offset + 3], (address + offset) & 0xFFFF)
        out.append(insn)
        offset += len(insn.data)
    return out
