"""Original CC0 cartridge fixtures. Rebuild program.json with tools/make_gba_native_fixture.py."""
import hashlib
import json
import struct
from pathlib import Path

from decompnet.gba_native import PROFILE_SCHEMA

PROGRAM = json.loads((Path(__file__).parent/'gba-native/program.json').read_text())


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
    """Original ARM IO-read timing program; mGBA 0.10.5 gives 7 + 6*N ticks."""
    words = [0,0xe3a00000,0xe1c400b0,0xe3a00080,0xe1c400b2]
    words += [0xe2877001]*instructions
    words += [0xe1d400b0,0xe3a06402,0xe5860000,0xeafffffe,0x04000100]
    words[0] = 0xe59f4000 | (len(words)-3)*4
    data=bytearray(0xc0)+bytearray(struct.pack('<'+'I'*len(words),*words))
    struct.pack_into('<I',data,0,0xea00002e)
    data[0xa0:0xac]=b'TIMER-MICRO!';data[0xac:0xb0]=b'TSTE';data[0xb2]=0x96
    data[0xbd]=(-(sum(data[0xa0:0xbd])+0x19))&255
    return bytes(data), dict(schema=PROFILE_SCHEMA,input_sha256=hashlib.sha256(data).hexdigest())
