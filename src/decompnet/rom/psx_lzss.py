"""Heartbeat's zero-initialized 4 KiB LZSS stream, with 3..18 byte matches.

The wire format is documented by the DQIV PSX format research linked in the
PS1 guide. This implementation bounds output by the archive's declared size.
"""

from .n64 import RomError


def decode(source, size):
    if not 0 <= size <= 16 << 20:
        raise RomError("Heartbeat decoded member exceeds 16 MiB")
    ring, cursor, output, at = bytearray(4096), 4078, bytearray(), 0
    while len(output) < size:
        if at >= len(source):
            raise RomError("truncated Heartbeat LZSS flags")
        flags = source[at]
        at += 1
        for bit in range(8):
            if len(output) >= size:
                break
            literal = flags & (1 << bit)
            count = 1 if literal else 2
            if at + count > len(source):
                raise RomError("truncated Heartbeat LZSS token")
            if literal:
                values = [source[at]]
            else:
                offset = source[at] | ((source[at + 1] & 0xF0) << 4)
                values = range((source[at + 1] & 15) + 3)
            at += count
            for value in values:
                byte = value if literal else ring[(offset + value) & 4095]
                ring[cursor] = byte
                cursor = (cursor + 1) & 4095
                output.append(byte)
    # A final token may overrun the declared size. DQVII also stores a full
    # zero terminator word when the token stream already ends word-aligned.
    if len(source) - at > 4 or any(source[at:]):
        raise RomError("Heartbeat LZSS has unexplained trailing bytes")
    return bytes(output[:size])


def encode(data):
    data = bytes(data)
    if len(data) > 16 << 20:
        raise RomError("Heartbeat decoded member exceeds 16 MiB")
    output, heads = bytearray(), {}
    previous, keys = [-1] * 4096, [None] * 4096
    position = 0
    while position < len(data):
        flag_at = len(output)
        output.append(0)
        for bit in range(8):
            if position >= len(data):
                break
            key = data[position:position + 3]
            candidate, best, distance, attempts = heads.get(key, -1), 0, 0, 0
            while candidate >= max(0, position - 4095) and candidate < position and attempts < 64:
                length = 0
                while length < min(18, len(data) - position) and data[candidate + length] == data[position + length]:
                    length += 1
                if length > best:
                    best, distance = length, candidate
                if best == 18:
                    break
                candidate = previous[candidate & 4095]
                attempts += 1
            count = best if best >= 3 else 1
            if count == 1:
                output[flag_at] |= 1 << bit
                output.append(data[position])
            else:
                offset = (4078 + distance) & 4095
                output += bytes([offset & 255, ((offset >> 4) & 0xF0) | (count - 3)])
            for inserted in range(position, position + count):
                slot = inserted & 4095
                expired = keys[slot]
                if expired is not None and heads.get(expired) == inserted - 4096:
                    del heads[expired]
                key = data[inserted:inserted + 3]
                previous[slot] = heads.get(key, -1)
                keys[slot], heads[key] = key, inserted
            position += count
    output += bytes(-len(output) % 4)
    return bytes(output)
