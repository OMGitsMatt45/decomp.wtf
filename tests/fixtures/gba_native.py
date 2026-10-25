"""Original CC0 cartridge fixtures. Rebuild program.json with tools/make_gba_native_fixture.py."""
import hashlib
import json
import struct
from pathlib import Path

from decompnet.gba_native import PROFILE_SCHEMA

PROGRAM = json.loads((Path(__file__).parent/'gba-native/program.json').read_text())


def bios_sound(mode="fixed-loop"):
    """Original service/mixer cartridge; requires a separately supplied BIOS."""
    program=json.loads((Path(__file__).parent/'gba-native/bios-sound.json').read_text())
    data=bytearray.fromhex(program['hex'])
    if mode not in ('fixed-loop','resampled-loop','one-shot'):
        raise ValueError('unknown original sound fixture')
    if mode!='fixed-loop':
        offset=data.index(struct.pack('<I',0x607f0880))
        struct.pack_into('<I',data,offset,0x607f0080)
    if mode=='one-shot':
        struct.pack_into('<H',data,program['symbols']['wave']-0x08000000+2,0)
    data[0xa0:0xac]=b'BIOS-SOUND!!';data[0xac:0xb0]=b'TSTE';data[0xb2]=0x96
    data[0xbd]=(-(sum(data[0xa0:0xbd])+0x19))&255
    data.extend(bytes(262148-len(data)))
    symbols=program['symbols']
    profile=dict(schema=PROFILE_SCHEMA,input_sha256=hashlib.sha256(data).hexdigest(),
        entries=[dict(address=symbols[name]&~1,mode=mode) for name,mode in
            (('irq','arm'),('music_callback','arm'),('thumb_on','thumb'))])
    return bytes(data),profile


def hardware():
    data = bytearray.fromhex(PROGRAM['hex'])
    # The copied routine's tail is readable in ROM, allowing the feedback recorder
    # to identify its source with a 32-byte signature, as it does for retail code.
    data.extend(bytes(32))
    data[0xa0:0xac] = b'ORIGINAL-GBA'
    data[0xac:0xb0] = b'TSTE'
    data[0xb2] = 0x96
    data[0xbd] = (-(sum(data[0xa0:0xbd])+0x19)) & 255
    symbols = PROGRAM['symbols']
    profile = dict(schema=PROFILE_SCHEMA, input_sha256=hashlib.sha256(data).hexdigest(),
        entries=[dict(address=symbols[n], mode=m) for n,m in (('thumb_code','thumb'), ('irq','arm'))],
        ram_code=[dict(rom=symbols['ram_source'], address=0x03000000,
                       size=symbols['ram_end']-symbols['ram_source'], mode='arm'),
                  dict(rom=symbols['short_source'], address=0x03000040, size=4, mode='thumb')])
    return bytes(data), profile


def timer_micro(instructions):
    """Original ARM IO reads followed by MOV and literal LDR; both give 7+6*N.

    Pad beyond 256 KiB so mGBA's heuristic cannot load a cartridge-ROM timing
    probe into multiboot EWRAM because it contains a literal EWRAM pointer.
    """
    words = [0,0xe3a00000,0xe1c400b0,0xe3a00080,0xe1c400b2]
    words += [0xe2877001]*instructions
    words += [0xe1d400b0,0xe3a06402,0xe5860000]
    # Disable, reload and restart before the second measurement.
    words += [0xe3a00000,0xe1c400b2,0xe1c400b0,0xe3a00080,0xe1c400b2]
    words += [0xe2877001]*instructions
    words += [0xe1d400b0]
    literal_load=len(words)
    words += [0,0xe5860004,0xeafffffe,0x04000100,0x02000000]
    words[0] = 0xe59f4000 | (len(words)-4)*4
    words[literal_load] = 0xe59f6000 | (len(words)-literal_load-3)*4
    data=bytearray(0xc0)+bytearray(struct.pack('<'+'I'*len(words),*words))
    data.extend(bytes(262148-len(data)))
    struct.pack_into('<I',data,0,0xea00002e)
    data[0xa0:0xac]=b'TIMER-MICRO!';data[0xac:0xb0]=b'TSTE';data[0xb2]=0x96
    data[0xbd]=(-(sum(data[0xa0:0xbd])+0x19))&255
    return bytes(data), dict(schema=PROFILE_SCHEMA,input_sha256=hashlib.sha256(data).hexdigest())


def bios_pipeline():
    """Original CC0 firmware and cartridge: pipeline latches and a firmware IRQ.

    The cartridge calls SWI 0, reads protected BIOS words/halfwords/bytes, calls
    a Thumb BIOS leaf, then enables timer 0. The BIOS IRQ disables/acknowledges
    the timer, stores 99 and calls a cartridge callback that stores 77 in EWRAM.
    mGBA 0.10.5 independently runs these bytes.
    """
    words = [
        0xe3a04402,0xef000000,0xe4840004,0xe3a05000,  # EWRAM pointer, SWI, store
        0xe5950000,0xe4840004,0xe1d500b2,0xe4840004,  # protected word/halfword
        0xe5d50001,0xe4840004,0xe5950100,0xe4840004,  # byte and another address
        0xe3a00c01,0xe2800001,0xe28fe000,0xe12fff10,  # Thumb BIOS call at 0x101
        0xe5950000,0xe4840004,0xe1d500b2,0xe4840004,
        0xe5d50001,0xe4840004,
        0xe59f0050,0xe59f1050,0xe5810000,             # cartridge IRQ callback
        0xe3a00301,0xe2800c02,0xe3a01008,0xe1c010b0,  # IE = timer 0
        0xe3a01001,0xe1c010b8,                        # IME = 1
        0xe3a00301,0xe2800c01,0xe3a01000,0xe1c010b0,
        0xe3a010c0,0xe1c010b2,                        # timer 0 reload/control
        0xe5950000,0xe5840000,0xeafffffc,             # retain IRQ exit latch
        0xe3a00402,0xe3a0104d,0xe5801044,0xe12fff1e,  # callback stores 77
        0x08000160,0x03007ffc,
    ]
    data=bytearray(0xc0)+bytearray(struct.pack('<'+'I'*len(words),*words))
    struct.pack_into('<I',data,0,0xea00002e)
    data[0xa0:0xac]=b'BIOS-LATCH!!';data[0xac:0xb0]=b'TSTE';data[0xb2]=0x96
    data[0xbd]=(-(sum(data[0xa0:0xbd])+0x19))&255
    image=bytearray(16384)
    def put(address, values):
        struct.pack_into('<'+'I'*len(values),image,address,*values)
    put(0,[0xea00000e,0xea00000d,0xea00000c,0xea00000b,0xea00000a,0xea000009,0xea000018])
    put(0x40,[0xe3a01c02,0xe5910000,0xe1b0f00e,0xe1a00000,0x12345678])
    put(0x80,[0xe92d4007,0xe3a00301,0xe2800c01,0xe3a01000,0xe1c010b2,
        0xe2800c01,0xe3a01008,0xe1c010b2,0xe3a00402,0xe3a01063,
        0xe5801040,0xe59f2018,0xe5922000,0xe1a0e00f,0xe12fff12,
        0xe8bd4007,0xe25ef004,0xe1a00000,0x31415926,0x03007ffc])
    put(0x100,[0x46c04770,0x00005aa5])  # bx lr, nop; next prefetched halfword
    put(0x200,[0x89abcdef])
    profile=dict(schema=PROFILE_SCHEMA,input_sha256=hashlib.sha256(data).hexdigest(),
        entries=[dict(address=address,mode='arm') for address in (0x08000100,0x08000160)])
    return (bytes(data),profile),bytes(image)
