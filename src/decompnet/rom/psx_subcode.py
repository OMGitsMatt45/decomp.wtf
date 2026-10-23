"""Validate and retime ordinary interleaved audio Q, retaining P and R-W bits."""

import binascii

from .n64 import RomError


def bcd(byte, limit=100):
    value = (byte >> 4) * 10 + (byte & 15)
    if byte >> 4 > 9 or byte & 15 > 9 or value >= limit:
        raise RomError("nonstandard raw subcode BCD needs mastering/protection review")
    return value


def position(data):
    return (bcd(data[0]) * 60 + bcd(data[1], 60)) * 75 + bcd(data[2], 75)


def msf(frames):
    if not 0 <= frames < 450000:
        raise RomError("retimed raw subcode exceeds the CD time range")
    values = frames // 4500, frames // 75 % 60, frames % 75
    return bytes((v // 10 << 4) | (v % 10) for v in values)


def q_channel(raw):
    if len(raw) != 96:
        raise RomError("raw subcode must contain 96 interleaved bytes")
    return bytes(sum(((raw[byte * 8 + bit] >> 6) & 1) << (7 - bit) for bit in range(8)) for byte in range(12))


def crc(data):
    return (binascii.crc_hqx(data, 0) ^ 65535).to_bytes(2, "big")


def retime(raw, shift, *, number, absolute, relative, pregap=False):
    """Only validated ADR 1 position / ADR 2 MCN / ADR 3 ISRC packets change."""
    q = bytearray(q_channel(raw))
    if not any(q):
        return raw  # Missing subcode stays missing.
    if q[10:] != crc(q[:10]) or q[0] & 0x40:
        raise RomError("nonstandard raw subcode CRC/control needs mastering/protection review")
    adr = q[0] & 15
    if adr == 1:
        index = bcd(q[2])
        if bcd(q[1]) != number or q[6] or position(q[7:10]) != absolute or (index == 0) != pregap:
            raise RomError("raw subcode position disagrees with its CHD track metadata")
        # Captures use both countdown boundary conventions; keep either intact.
        allowed = (relative, relative - 1) if pregap else (relative,)
        if position(q[3:6]) not in allowed:
            raise RomError("raw subcode relative time disagrees with its CHD track metadata")
        q[7:10] = msf(absolute + shift)
    elif adr in (2, 3):
        if bcd(q[9], 75) != absolute % 75:
            raise RomError("raw subcode catalogue/ISRC time disagrees with its CHD track metadata")
        if adr == 2:
            for byte in q[1:7]:
                bcd(byte)
            if q[7] >> 4 > 9 or q[7] & 15 or q[8]:
                raise RomError("nonstandard raw subcode catalogue payload")
        else:
            characters = int.from_bytes(q[1:5], "big") >> 2
            codes = [(characters >> ((4 - i) * 6)) & 63 for i in range(5)]
            if q[4] & 3 or any(not 17 <= c <= 42 for c in codes[:2]) or any(
                    not (c <= 9 or 17 <= c <= 42) for c in codes[2:]) or q[8] & 15 or q[8] >> 4 > 9:
                raise RomError("nonstandard raw subcode ISRC payload")
            for byte in q[5:8]:
                bcd(byte)
        q[9] = msf(absolute + shift)[2]
    else:
        raise RomError("unknown raw subcode ADR needs mastering/protection review")
    q[10:] = crc(q[:10])
    result = bytearray(raw)
    for bit in range(96):
        result[bit] = (result[bit] & 0xBF) | (((q[bit // 8] >> (7 - bit % 8)) & 1) << 6)
    return bytes(result)
