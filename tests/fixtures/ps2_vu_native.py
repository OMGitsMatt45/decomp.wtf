"""CC0 original VU programs for arithmetic, pipelines, memory and branches."""
import struct

NOP=0x2ff
LOWER_NOP=0x8000033c


def upper(op,fs=1,ft=2,fd=3,dest=15):
    return (dest<<21)|(ft<<16)|(fs<<11)|(fd<<6)|op


def program_pairs():
    arithmetic=[(LOWER_NOP,upper(0x28)),(LOWER_NOP,upper(0x2a,fs=3,fd=4)),
        (LOWER_NOP,upper(0x29,fs=4,ft=3,fd=5)),(LOWER_NOP,upper(0x2c,fs=5,fd=6)),
        (LOWER_NOP,upper(0x2b,fs=6,fd=7)),(LOWER_NOP,upper(0x2f,fs=7,fd=8)),
        (LOWER_NOP,NOP|0x40000000),(LOWER_NOP,NOP)]
    memory=[((15<<21)|(1<<16),NOP),((15<<21)|(2<<16)|1,NOP),
        (LOWER_NOP,upper(0x28)),((1<<25)|(15<<21)|(3<<11)|2,NOP),
        (LOWER_NOP,NOP|0x40000000),(LOWER_NOP,NOP)]
    loop=[((8<<25)|(3<<16)|3,NOP),(LOWER_NOP,NOP),
        ((9<<25)|(3<<16)|(3<<11)|1,NOP),(LOWER_NOP,upper(0x28,fs=3,fd=3)),
        ((0x29<<25)|(3<<11)|0x7fd,NOP),(LOWER_NOP,NOP),
        (LOWER_NOP,NOP|0x40000000),(LOWER_NOP,NOP)]
    immediate=[(0x3f800000,upper(0x28)|0x80000000),(LOWER_NOP,upper(0x22,fd=4)),
        (LOWER_NOP,upper(0x1e,fs=4,fd=5)),(LOWER_NOP,NOP|0x40000000),(LOWER_NOP,NOP)]
    return [arithmetic,memory,loop,immediate]


def programs():
    return [b''.join(struct.pack('<II',lower,high) for lower,high in pairs) for pairs in program_pairs()]
