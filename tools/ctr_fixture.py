"""CC0 original 3DS executables. No Nintendo SDK, game, keys or firmware."""
import hashlib
from pathlib import Path
import struct

BASE = 0x00100000


def fixture(kind='arm'):
    programs = {
        # Append an unreachable Thumb return for strict/compatibility coverage tests.
        'services': bytes.fromhex(Path(__file__).with_name('fixtures').joinpath('ctr-services.hex').read_text())+b'\x70\x47',
        'arm': struct.pack('<IIII', 0xe3a00007, 0xe3a01005, 0xe0800001, 0xef000003),
        # ldr r3, literal; blx r3; svc ExitProcess; pointer; Thumb movs r0,42; bx lr
        'thumb': struct.pack('<IIIIHH', 0xe59f3004, 0xe12fff33, 0xef000003, BASE+0x11, 0x202a, 0x4770),
        # float 1.0 -> s0; s0+s0 -> s0; return IEEE float bits for 2.0
        'vfp': struct.pack('<IIIIII', 0xe59f000c, 0xee000a10, 0xee300a00, 0xee100a10, 0xef000003, 0x3f800000),
        # The callback address exists only in .data, reached through a table.
        'data-callback': struct.pack('<IIIII',0xe59f3008,0xe5933000,0xe12fff33,0xef000003,BASE+0x2000)
            +bytes(12)+struct.pack('<II',0xe3a0002a,0xe12fff1e),
        # Three self-relative callback slots; none stores an absolute code
        # pointer. The first reaches Thumb code, which ARM gap scanning misses.
        'relative-callbacks': struct.pack('<6I6H',0xe59f300c,0xe5930000,0xe0833000,
            0xe12fff33,0xef000003,BASE+0x1000,0x202a,0x4770,0x202b,0x4770,0x202c,0x4770),
        'unsupported-service': struct.pack('<II', 0xef000001, 0xef000003),
        'unknown-target': struct.pack('<II', 0xe3a03000, 0xe12fff13),
        'unsupported-opcode': struct.pack('<II', 0xee100f10, 0xef000003),
        'read-only-write': struct.pack('<IIII', 0xe59f1004, 0xe5810000, 0xef000003, BASE),
        'bss': struct.pack('<IIII', 0xe59f1004, 0xe5910000, 0xef000003, BASE+0x2004),
        'loop': struct.pack('<I', 0xeafffffe),
    }
    program='arm' if kind=='blz-arm' else 'relative-callbacks' if kind=='hidden-callback' else kind
    text = programs[program]
    data=struct.pack('<I',BASE+0x20) if kind=='data-callback' else b'DATA'
    rodata=b'RO!!'
    if kind in ('relative-callbacks','hidden-callback'):
        count=3 if kind=='relative-callbacks' else 1
        rodata=struct.pack('<'+'I'*count,*((BASE+0x19+4*i-(BASE+0x1000+4*i))&0xffffffff for i in range(count)))
    code = text+bytes(0x1000-len(text))+rodata+bytes(0x1000-len(rodata))+data
    if kind=='blz-arm':
        code=bytes.fromhex(Path(__file__).with_name('fixtures').joinpath('ctr-arm-code.blz.hex').read_text())
    exefs_size = (0x200+len(code)+0x1ff)&~0x1ff
    out = bytearray(0xa00+exefs_size)
    out[0x100:0x104] = b'NCCH'
    struct.pack_into('<I', out, 0x104, len(out)//0x200)
    struct.pack_into('<Q', out, 0x118, 0x000400000ff3de00)
    struct.pack_into('<I', out, 0x180, 0x400)
    out[0x18d], out[0x18f] = 2, 4
    struct.pack_into('<II', out, 0x1a0, 5, exefs_size//0x200)
    out[0x200:0x208] = b'CTRTEST\0'
    if kind=='blz-arm':out[0x20d]=1
    for at, values in ((0x210, (BASE, 1, len(text))), (0x220, (BASE+0x1000, 1, len(rodata))),
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


def cro(name='OriginalFixture', *, thumb=False, save=False):
    """CC0 module exporting an original return-42 or persistent-save program."""
    code=struct.pack('<HH',0x202a,0x4770) if thumb else struct.pack('<II',0xe3a0002a,0xe12fff1e)
    if save:
        assert not thumb
        code=bytes.fromhex(Path(__file__).with_name('fixtures').joinpath('ctr-save.hex').read_text())
    out=bytearray(0x200+len(code))
    out[0x80:0x84]=b'CRO0'
    for at,value in ((0xc0,0x180),(0xc8,0x138),(0xcc,1),(0x138,0x200),
                     (0x13c,len(code)),(0xd8,0x150),(0xdc,1),(0x150,0x10 if thumb else 0)):
        struct.pack_into('<I',out,at,value)
    # Thumb pointer is the code offset + 1, encoded as segment tag offset << 4.
    encoded=name.encode('ascii')
    assert len(encoded)<0x80
    out[0x180:0x180+len(encoded)]=encoded
    out[0x200:]=code
    return bytes(out)


def with_romfs(raw, entries, *, directory=None):
    """Append a flat original IVFC/RomFS; metadata and payloads are independent.

    No retail assets or hash-tree acceptance claim. The importer and runtime
    use the whole-image identity and independently hashed module bytes.
    """
    files=bytearray();offsets=[];payload=bytearray()
    for name,data in entries:
        name=name.encode('utf-16-le');at=len(files);offsets.append(at)
        files.extend(struct.pack('<IIQQII',0 if directory is None else 0x18,0xffffffff,len(payload),len(data),0xffffffff,len(name))+name)
        files.extend(bytes((-len(files))%4));payload.extend(data)
    for index,at in enumerate(offsets[:-1]):
        struct.pack_into('<I',files,at+4,offsets[index+1])
    first=offsets[0] if offsets else 0xffffffff
    if directory is None:
        dirs=struct.pack('<6I',0,0xffffffff,0xffffffff,first,0xffffffff,0)
    else:
        name=directory.encode('utf-16-le')
        dirs=struct.pack('<6I',0,0xffffffff,0x18,0xffffffff,0xffffffff,0)
        dirs+=struct.pack('<6I',0,0xffffffff,0xffffffff,first,0xffffffff,len(name))+name
        dirs+=bytes((-len(dirs))%4)
    file_meta=0x28+4+len(dirs)+4
    data_offset=(file_meta+len(files)+15)&~15
    level=bytearray(data_offset+len(payload))
    struct.pack_into('<10I',level,0,0x28,0x28,4,0x2c,len(dirs),file_meta-4,4,file_meta,len(files),data_offset)
    level[0x2c:0x2c+len(dirs)]=dirs
    level[file_meta:file_meta+len(files)]=files
    level[data_offset:]=payload
    ivfc=bytearray(0x1000)+level
    ivfc[:4]=b'IVFC'
    struct.pack_into('<I',ivfc,4,0x10000)
    struct.pack_into('<Q',ivfc,0x44,len(level))
    struct.pack_into('<I',ivfc,0x4c,12)
    ivfc.extend(bytes((-len(ivfc))%0x200))
    out=bytearray(raw);out.extend(bytes((-len(out))%0x200));start=len(out)
    out.extend(ivfc)
    struct.pack_into('<I',out,0x104,len(out)//0x200)
    struct.pack_into('<II',out,0x1b0,start//0x200,len(ivfc)//0x200)
    return bytes(out)


if __name__=='__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--kind', choices=('arm','blz-arm','thumb','vfp','bss','data-callback','relative-callbacks','hidden-callback','services','unsupported-service','unknown-target','unsupported-opcode','read-only-write','loop'), default='arm')
    parser.add_argument('--cartridge', action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; preserve it and choose another path')
    raw=fixture(args.kind)
    args.output.write_bytes(cartridge(raw) if args.cartridge else raw)
