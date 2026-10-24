"""Original CC0 program inputs for the full DS native runtime adapter."""
import json
import hashlib
import struct
from pathlib import Path

from .nds_static import image, PROGRAM


def dual_cpu():
    raw,profile=image()
    profile.pop('hooks');profile.pop('save_region')
    symbols=PROGRAM['arm9']['symbols']
    profile['code']['arm9'].append(dict(address=symbols['loader'],
        size=symbols['overlay1_source']-symbols['loader'],mode='arm'))
    return raw,profile


def hardware():
    program=json.loads((Path(__file__).parent/'nds-hardware/program.json').read_text())
    ranges=[]
    symbols=program['arm9']['symbols']
    for begin,end in (('_start','main_end'),('save_read','save_read_end'),
                      ('save_write','save_write_end'),('irq_start','irq_end')):
        ranges.append(dict(address=symbols[begin],size=symbols[end]-symbols[begin],mode='arm'))
    ranges.append(dict(address=symbols['thumb_start'],size=symbols['thumb_end']-symbols['thumb_start'],mode='thumb'))
    symbols7=program['arm7']['symbols']
    raw,profile=image(bytes.fromhex(program['arm9']['hex']),bytes.fromhex(program['arm7']['hex']),
        code9=ranges,code7=[dict(address=symbols7['_start'],size=symbols7['main_end']-symbols7['_start'],mode='arm')],
        overlays=False)
    profile.pop('save_region')
    raw=bytearray(raw);raw.extend(bytes(0x8200-len(raw)))
    for i in range(128):struct.pack_into('<I',raw,0x8000+i*4,0xd5000000+i)
    raw=bytes(raw);profile['input_sha256']=hashlib.sha256(raw).hexdigest()
    profile['observe_words']=[0x02010000+i*4 for i in range(13)]
    return raw,profile
