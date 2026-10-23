"""Bounded decoder for CHD's headerless 16-bit stereo FLAC frames.

CHD appends raw deflate subcode immediately after the FLAC frames. Decode the
declared number of samples and return the exact boundary, including frame CRCs.
No audio device, native library or external tool is needed.
"""

import struct

from .errors import RomError


class Bits:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, width):
        if width < 0 or self.pos + width > len(self.data) * 8:
            raise RomError("truncated CHD FLAC frame")
        result = 0
        while width:
            byte, bit = divmod(self.pos, 8)
            take = min(width, 8 - bit)
            result = (result << take) | ((self.data[byte] >> (8 - bit - take)) & ((1 << take) - 1))
            self.pos += take
            width -= take
        return result

    def signed(self, width):
        value = self.read(width)
        return value - (1 << width) if width and value & (1 << (width - 1)) else value

    def unary(self):
        start = self.pos
        while not self.read(1):
            if self.pos - start > 1 << 20:
                raise RomError("invalid CHD FLAC Rice residual")
        return self.pos - start - 1

    def align(self):
        if self.read(-self.pos % 8):
            raise RomError("nonzero CHD FLAC padding")


def crc(data, width, polynomial):
    result = 0
    for byte in data:
        result ^= byte << (width - 8)
        for _ in range(8):
            result = ((result << 1) ^ (polynomial if result & (1 << (width - 1)) else 0)) & ((1 << width) - 1)
    return result


def _subframe(bits, count, width):
    if bits.read(1):
        raise RomError("invalid CHD FLAC subframe")
    kind, wasted = bits.read(6), bits.read(1)
    wasted = bits.unary() + 1 if wasted else 0
    width -= wasted
    if width <= 0:
        raise RomError("invalid CHD FLAC sample width")
    if kind == 0:
        values = [bits.signed(width)] * count
    elif kind == 1:
        values = [bits.signed(width) for _ in range(count)]
    else:
        if 8 <= kind <= 12:
            order = kind - 8
            coefficients = ((), (1,), (2, -1), (3, -3, 1), (4, -6, 4, -1))[order]
            shift = 0
        elif 32 <= kind <= 63:
            order = kind - 31
        else:
            raise RomError("unsupported CHD FLAC subframe")
        if order > count:
            raise RomError("invalid CHD FLAC predictor order")
        values = [bits.signed(width) for _ in range(order)]
        if kind >= 32:
            precision = bits.read(4) + 1
            if precision == 16:
                raise RomError("invalid CHD FLAC LPC precision")
            shift = bits.signed(5)
            coefficients = [bits.signed(precision) for _ in range(order)]
        method, partition = bits.read(2), bits.read(4)
        if method > 1 or count % (1 << partition) or (count >> partition) < order:
            raise RomError("invalid CHD FLAC residual partition")
        rice_width = 4 + method
        residuals = []
        for part in range(1 << partition):
            size = (count >> partition) - (order if part == 0 else 0)
            parameter = bits.read(rice_width)
            if parameter == (1 << rice_width) - 1:
                raw_width = bits.read(5)
                residuals.extend(bits.signed(raw_width) for _ in range(size))
            else:
                for _ in range(size):
                    value = (bits.unary() << parameter) | bits.read(parameter)
                    residuals.append((value >> 1) ^ -(value & 1))
        for value in residuals:
            predicted = sum(c * values[-i - 1] for i, c in enumerate(coefficients))
            values.append(value + (predicted >> shift if shift >= 0 else predicted << -shift))
    return [value << wasted for value in values]


def decode(data, samples):
    """Return big-endian stereo PCM and consumed bytes, excluding appended subcode."""
    bits, output = Bits(data), bytearray()
    while len(output) < samples * 4:
        start = bits.pos // 8
        if bits.read(14) != 0x3FFE or bits.read(1):
            raise RomError("invalid CHD FLAC frame sync")
        bits.read(1)  # fixed/variable blocking strategy
        block, rate, channels, width = bits.read(4), bits.read(4), bits.read(4), bits.read(3)
        if bits.read(1) or width not in (0, 4) or channels not in (1, 8, 9, 10) or rate == 15:
            raise RomError("CHD FLAC requires 16-bit stereo audio")
        first = bits.read(8)  # UTF-8 coded frame/sample number
        if first >= 128:
            leading = 0
            for mask in (128, 64, 32, 16, 8, 4, 2, 1):
                if not first & mask:
                    break
                leading += 1
            if not 2 <= leading <= 7:
                raise RomError("invalid CHD FLAC frame number")
            for _ in range(leading - 1):
                if bits.read(8) & 0xC0 != 0x80:
                    raise RomError("invalid CHD FLAC frame number")
        if block == 1:
            count = 192
        elif 2 <= block <= 5:
            count = 576 << (block - 2)
        elif block in (6, 7):
            count = bits.read(8 if block == 6 else 16) + 1
        elif block >= 8:
            count = 256 << (block - 8)
        else:
            raise RomError("invalid CHD FLAC block size")
        if count > samples - len(output) // 4:
            raise RomError("CHD FLAC exceeds its declared sample count")
        if rate in (12, 13, 14):
            bits.read(8 if rate == 12 else 16)
        header_end = bits.pos // 8
        if bits.read(8) != crc(data[start:header_end], 8, 7):
            raise RomError("CHD FLAC header checksum mismatch")
        left = _subframe(bits, count, 17 if channels == 9 else 16)
        right = _subframe(bits, count, 17 if channels in (8, 10) else 16)
        bits.align()
        end = bits.pos // 8
        if bits.read(16) != crc(data[start:end], 16, 0x8005):
            raise RomError("CHD FLAC frame checksum mismatch")
        for a, b in zip(left, right):
            if channels == 8:
                b = a - b
            elif channels == 9:
                a += b
            elif channels == 10:
                mid = (a << 1) | (b & 1)
                a, b = (mid + b) >> 1, (mid - b) >> 1
            if not -32768 <= a < 32768 or not -32768 <= b < 32768:
                raise RomError("CHD FLAC sample overflow")
            output += struct.pack(">hh", a, b)
    return bytes(output), bits.pos // 8
