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


def mixed_arm_switch(wide=False):
    from .nds_static import simple
    words=[0]
    calls=[]
    values=(0,299,300) if wide else (0,1,2,3)
    def immediate(value):
        for rotate in range(16):
            encoded=((value<<(2*rotate))|(value>>(32-2*rotate)))&0xffffffff
            if encoded<256:return rotate<<8|encoded
        raise ValueError('fixture immediate is not encodable')
    for index,value in enumerate(values):
        try:words.append(0xe3a00000|immediate(value))
        except ValueError:
            words.extend([0xe3a00000|immediate(value&~255),0xe3800000|(value&255)])
        calls.append(len(words));words.append(0)
        words.append(0xe5840000|index*4)
    words.append(0xeafffffe)
    main_size=len(words)*4;switch=len(words)
    if wide:
        words.extend([0xe92d4008,0xe3a02001,0xe2621000|immediate(300),0xe1500001,0x908ff100,0xe8bd8008])
        for index in range(300):words.append(0xe8bd8008 if index==299 else 0xea000000|(300-index-2))
        words.extend([0xe3a0004d,0xe8bd8008])
    else:
        words.extend([0xe92d4008,0xe3500002,0x908ff100,0xe8bd8008,
                      0xea000001,0xe8bd8008,0xea000001,0xe3a0000b,0xe8bd8008,
                      0xe3a00016,0xe8bd8008])
    end=len(words)*4
    words[0]=0xe59f4000|(end-8)
    words.append(0x02010000)
    for index in calls:words[index]=0xeb000000|((switch-index-2)&0xffffff)
    raw,profile=simple(struct.pack('<'+'I'*len(words),*words),struct.pack('<I',0xeafffffe),code_size9=main_size)
    profile.pop('save_region');profile['observe_words']=[0x02010000+4*i for i in range(len(values))]
    profile['code']['arm9'].append(dict(address=0x02000000+switch*4,size=end-switch*4,mode='arm'))
    return raw,profile


def hardware():
    program=json.loads((Path(__file__).parent/'nds-hardware/program.json').read_text())
    ranges=[]
    symbols=program['arm9']['symbols']
    for begin,end in (('_start','main_end'),('save_read','save_read_end'),
                      ('save_write','save_write_end'),('irq_start','irq_end')):
        ranges.append(dict(address=symbols[begin],size=symbols[end]-symbols[begin],mode='arm'))
    ranges.append(dict(address=symbols['thumb_start'],size=symbols['thumb_end']-symbols['thumb_start'],mode='thumb'))
    for begin,end in (('shared_start','shared_end'),('shared_exit','shared_exit_end'),
                      ('regular_start','regular_end'),('child_start','child_end'),('large_start','large_end')):
        ranges.append(dict(address=symbols[begin],size=symbols[end]-symbols[begin],mode='thumb'))
    symbols7=program['arm7']['symbols']
    raw,profile=image(bytes.fromhex(program['arm9']['hex']),bytes.fromhex(program['arm7']['hex']),
        code9=ranges,code7=[dict(address=symbols7['_start'],size=symbols7['main_end']-symbols7['_start'],mode='arm')],
        overlays=False)
    profile.pop('save_region')
    raw=bytearray(raw);raw.extend(bytes(0x8200-len(raw)))
    for i in range(128):struct.pack_into('<I',raw,0x8000+i*4,0xd5000000+i)
    raw=bytes(raw);profile['input_sha256']=hashlib.sha256(raw).hexdigest()
    profile['observe_words']=[0x02010000+i*4 for i in range(17)]
    return raw,profile


def video():
    program=json.loads((Path(__file__).parent/'nds-video/program.json').read_text())
    code=lambda cpu:[dict(address=program[cpu]['symbols']['_start'],
        size=program[cpu]['symbols']['main_end']-program[cpu]['symbols']['_start'],mode='arm')]
    raw,profile=image(bytes.fromhex(program['arm9']['hex']),bytes.fromhex(program['arm7']['hex']),
        code9=code('arm9'),code7=code('arm7'),overlays=False)
    profile.pop('save_region');profile['observe_words']=[]
    return raw,profile
