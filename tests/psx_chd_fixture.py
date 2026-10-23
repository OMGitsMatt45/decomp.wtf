"""Original code/data, non-silent stereo PCM and raw subcode; no retail content."""

import struct

from .test_psx_disc import fixture
from .test_psx_modify import valid_raw


def decoded():
    data = valid_raw(fixture(), 2448, 24)
    audio, state = bytearray(), 0x12345678
    for frame in range(33):
        for sample in range(588):
            t = frame * 588 + sample
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            if frame < 8:
                a, b = ((t * 37) % 65536) - 32768, ((t * 19 + t * t // 83) % 65536) - 32768
            elif frame < 16:
                a, b = (state >> 16) - 32768, (state & 65535) - 32768
            elif frame < 24:
                a, b = 16384, -8192  # constant subframes with wasted bits
            else:
                a, b = ((t * 7) % 8192) - 4096, ((t * 7) % 8192) - 4095
            audio += struct.pack(">hh", a, b)
        audio += bytes((frame * 13 + i * 11) % 256 for i in range(96))
    audio[24 * 2448:32 * 2448] = audio[16 * 2448:24 * 2448]  # exercise CHD self-reference maps
    # CHD stores each CD track padded to four frames; these are opaque too.
    return data + bytes(2 * 2448) + audio + bytes(3 * 2448)


METADATA = [
    ("CHT2", "TRACK:1 TYPE:MODE2_RAW SUBTYPE:RW_RAW FRAMES:30 PREGAP:0 PGTYPE:MODE1 PGSUB:NONE POSTGAP:0", True),
    ("CHT2", "TRACK:2 TYPE:AUDIO SUBTYPE:RW_RAW FRAMES:33 PREGAP:150 PGTYPE:AUDIO PGSUB:RW_RAW POSTGAP:0", True),
    ("TEST", "Original opaque non-checksummed metadata", False),
]
