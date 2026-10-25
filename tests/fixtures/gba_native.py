"""Original CC0 cartridge fixtures. Rebuild program.json with tools/make_gba_native_fixture.py."""
import hashlib
import json
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
                       size=symbols['ram_end']-symbols['ram_source'], mode='arm')])
    return bytes(data), profile
