"""CC0 original 3DS executables. No Nintendo SDK, game, keys or firmware."""
import hashlib
from pathlib import Path
import struct

BASE = 0x00100000


def fixture(kind='arm'):
    programs = {
        'services': bytes.fromhex(Path(__file__).with_name('fixtures').joinpath('ctr-services.hex').read_text()),
        'arm': struct.pack('<IIII', 0xe3a00007, 0xe3a01005, 0xe0800001, 0xef000003),
        # ldr r3, literal; blx r3; svc ExitProcess; pointer; Thumb movs r0,42; bx lr
        'thumb': struct.pack('<IIIIHH', 0xe59f3004, 0xe12fff33, 0xef000003, BASE+0x11, 0x202a, 0x4770),
        # float 1.0 -> s0; s0+s0 -> s0; return IEEE float bits for 2.0
        'vfp': struct.pack('<IIIIII', 0xe59f000c, 0xee000a10, 0xee300a00, 0xee100a10, 0xef000003, 0x3f800000),
        # The callback address exists only in .data, reached through a table.
        'data-callback': struct.pack('<IIIII',0xe59f3008,0xe5933000,0xe12fff33,0xef000003,BASE+0x2000)
            +bytes(12)+struct.pack('<II',0xe3a0002a,0xe12fff1e),
        'unsupported-service': struct.pack('<II', 0xef000001, 0xef000003),
        'unknown-target': struct.pack('<II', 0xe3a03000, 0xe12fff13),
        'unsupported-opcode': struct.pack('<II', 0xee100f10, 0xef000003),
        'read-only-write': struct.pack('<IIII', 0xe59f1004, 0xe5810000, 0xef000003, BASE),
        'bss': struct.pack('<IIII', 0xe59f1004, 0xe5910000, 0xef000003, BASE+0x2004),
        'loop': struct.pack('<I', 0xeafffffe),
    }
    text = programs[kind]
    data=struct.pack('<I',BASE+0x20) if kind=='data-callback' else b'DATA'
    code = text+bytes(0x1000-len(text))+b'RO!!'+bytes(0xffc)+data
    exefs_size = (0x200+len(code)+0x1ff)&~0x1ff
    out = bytearray(0xa00+exefs_size)
    out[0x100:0x104] = b'NCCH'
    struct.pack_into('<I', out, 0x104, len(out)//0x200)
    struct.pack_into('<Q', out, 0x118, 0x000400000ff3de00)
    struct.pack_into('<I', out, 0x180, 0x400)
    out[0x18d], out[0x18f] = 2, 4
    struct.pack_into('<II', out, 0x1a0, 5, exefs_size//0x200)
    out[0x200:0x208] = b'CTRTEST\0'
    for at, values in ((0x210, (BASE, 1, len(text))), (0x220, (BASE+0x1000, 1, 4)),
                       (0x230, (BASE+0x2000, 1, 4))):
        struct.pack_into('<III', out, at, *values)
    struct.pack_into('<I', out, 0x23c, 16)
    struct.pack_into('<I', out, 0x21c, 0x4000)
    out[0xa00:0xa05] = b'.code'
    struct.pack_into('<II', out, 0xa08, 0, len(code))
    out[0xbe0:0xc00] = hashlib.sha256(code).digest()
    out[0xc00:0xc00+len(code)] = code
    return bytes(out)


def cartridge(raw):
    out = bytearray(0x4000+len(raw))
    out[0x100:0x104] = b'NCSD'
    struct.pack_into('<I', out, 0x104, len(out)//0x200)
    struct.pack_into('<II', out, 0x120, 0x20, len(raw)//0x200)
    out[0x4000:] = raw
    return bytes(out)


if __name__=='__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--kind', choices=('arm','thumb','vfp','bss','data-callback','services','unsupported-service','unknown-target','unsupported-opcode','read-only-write','loop'), default='arm')
    parser.add_argument('--cartridge', action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; preserve it and choose another path')
    raw=fixture(args.kind)
    args.output.write_bytes(cartridge(raw) if args.cartridge else raw)
