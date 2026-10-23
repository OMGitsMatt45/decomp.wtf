"""CD-ROM Mode 1 and Mode 2 Form 1 EDC and Reed-Solomon P/Q parity."""

from .errors import RomError

FORWARD, BACKWARD, EDC = [0] * 256, [0] * 256, [0] * 256
for _i in range(256):
    _j = (_i << 1) ^ (0x11D if _i & 0x80 else 0)
    FORWARD[_i], BACKWARD[_i ^ _j] = _j, _i
    _crc = _i
    for _ in range(8):
        _crc = (_crc >> 1) ^ (0xD8018001 if _crc & 1 else 0)
    EDC[_i] = _crc


def edc(data):
    result = 0
    for byte in data:
        result = (result >> 8) ^ EDC[(result ^ byte) & 255]
    return result.to_bytes(4, "little")


def _parity(source, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    result = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            value = source[index]
            index = (index + minor_inc) % size
            a = FORWARD[a ^ value]
            b ^= value
        a = BACKWARD[FORWARD[a] ^ b]
        result[major], result[major + major_count] = a, a ^ b
    return result


def corrected(sector):
    if len(sector) not in (2352, 2448) or sector[:12] != b"\0" + b"\xff" * 10 + b"\0":
        raise RomError("modified PS1 sectors require ordinary raw CD-ROM frames")
    result = bytearray(sector)
    if result[15] == 1:
        result[2064:2068] = edc(result[:2064])
        result[2068:2076] = bytes(8)
    elif result[15] == 2 and result[16:20] == result[20:24] and not result[18] & 0x20:
        result[2072:2076] = edc(result[16:2072])
    else:
        raise RomError("modified PS1 programs require Mode 1 or Mode 2 Form 1 sectors")
    return restore_parity(result)


def restore_parity(sector):
    """Restore only P/Q bytes removed by CHD; preserve the original EDC."""
    result = bytearray(sector)
    address = result[12:16]
    if result[15] == 2:
        result[12:16] = bytes(4)
    result[2076:2248] = _parity(result[12:2076], 86, 24, 2, 86)
    result[2248:2352] = _parity(result[12:2248], 52, 43, 86, 88)
    result[12:16] = address
    return bytes(result)


def replace(sector, payload):
    if len(payload) != 2048:
        raise RomError("a modified PS1 data sector must contain exactly 2048 bytes")
    skip = 16 if len(sector) >= 16 and sector[15] == 1 else 24
    if sector[skip:skip + 2048] == payload:
        return sector
    if corrected(sector) != sector:
        raise RomError("a changed sector has nonstandard original EDC/ECC; its mastering/protection needs review")
    result = bytearray(sector)
    result[skip:skip + 2048] = payload
    return corrected(result)
