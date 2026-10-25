"""Original CC0 DS programs, assembled from the adjacent documented sources."""
import hashlib
import json
from pathlib import Path
import struct

from decompnet.forks.scratch_dsd import crc16
from decompnet.nds_pc import SCHEMA

PROGRAM = json.loads((Path(__file__).parent/'nds-static/program.json').read_text())


def image(arm9=None, arm7=None, *, code9=None, code7=None, thumb7=False, overlays=True, overlay_add=7):
    p9,p7=PROGRAM['arm9'],PROGRAM['arm7']
    a9=bytearray(bytes.fromhex(p9['hex']) if arm9 is None else arm9)
    a7=bytes.fromhex(p7['hex']) if arm7 is None else arm7
    if overlays:
        offset=p9['symbols']['overlay1_source']-0x02000000
        struct.pack_into('<I',a9,offset,0xe2800000|overlay_add)
    raw=bytearray(0x3020)
    raw[:12]=b'STATIC TEST\0'
    raw[12:16]=b'TSTE'
    raw[0x10:0x12]=b'00'
    struct.pack_into('<4I',raw,0x20,0x1000,0x02000000,0x02000000,len(a9))
    struct.pack_into('<4I',raw,0x30,0x2000,0x03800000|thumb7,0x03800000,len(a7))
    raw[0x1000:0x1000+len(a9)]=a9
    raw[0x2000:0x2000+len(a7)]=a7
    if code9 is None:
        code9=[dict(address=0x02000000,size=p9['symbols']['main_end']-0x02000000,mode='arm'),
               dict(address=p9['symbols']['thumb_start'],size=p9['symbols']['thumb_end']-p9['symbols']['thumb_start'],mode='thumb')]
    if code7 is None:
        code7=[dict(address=0x03800000,size=p7['symbols']['main_end']-0x03800000,mode='arm')]
    profile=dict(schema=SCHEMA,processors=dict(arm9=dict(stack=0x023ff000),arm7=dict(stack=0x0380ff00)),
                 code=dict(arm9=code9,arm7=code7),observe_words=[0x02010000+i*4 for i in (0,1,2,3,4,5,8)],
                 save_region=dict(address=0x02010020,size=4))
    if overlays:
        struct.pack_into('<2I',raw,0x48,0x440,16)
        struct.pack_into('<2I',raw,0x50,0x400,64)
        for fid,add in enumerate((overlay_add,11)):
            offset=0x3000+fid*16
            struct.pack_into('<8I',raw,0x400+fid*32,fid+1,0x02020000,8,16,0,0,fid,0)
            struct.pack_into('<2I',raw,0x440+fid*8,offset,offset+8)
            struct.pack_into('<2I',raw,offset,0xe2800000|add,0xe12fff1e)
            profile['code']['arm9:ov'+str(fid+1)]=[dict(address=0x02020000,size=8,mode='arm')]
        profile['hooks']=[dict(cpu='arm9',address=p9['symbols']['loader'],mode='arm',service='load_overlay')]
    struct.pack_into('<H',raw,0x15e,crc16(raw[:0x15e]))
    profile['input_sha256']=hashlib.sha256(raw).hexdigest()
    return bytes(raw),profile


def simple(arm9,arm7=struct.pack('<I',0xe12fff1e),*,thumb7=False,code_size9=None,code_size7=None):
    return image(arm9,arm7,code9=[dict(address=0x02000000,size=code_size9 or len(arm9),mode='arm')],
                 code7=[dict(address=0x03800000,size=code_size7 or len(arm7),mode='thumb' if thumb7 else 'arm')],
                 thumb7=thumb7,overlays=False)


def arm_arithmetic():
    """Independent instruction encodings exercise carry/overflow and shift boundaries."""
    cases=[]
    for op in (2,3,4,5,6,7):
        for a,b,carry in ((0x7fffffff,1,1),(0xffffffff,0xffffffff,0),(0x80000000,1,1)):
            cases.append((0xe0102001 | (op<<21),a,b,carry))
    for op in (0,1,12,14,15):cases.append((0xe0102001 | (op<<21),0x8000ffff,0x12345678,1))
    for kind in range(4):
        for amount in (0,1,31,32,33,255):cases.append((0xe1b02110 | (kind<<5),0x80000001,amount,1))
    for kind in (1,2,3):cases.append((0xe1b02000 | (kind<<5),0x80000001,0,1))
    cases.append((0xe0120190,0xffffffff,7,0))  # MULS r2,r0,r1
    words=[];literals=[]
    def literal(register,value):
        literals.append((len(words),register,value));words.append(0)
    literal(5,0x02030000)
    for index,(instruction,a,b,carry) in enumerate(cases):
        literal(0,a);literal(1,b)
        words.extend([0xe3560000 | (0 if carry else 1),instruction,0xe3a04000])
        for condition,bit in ((4,8),(0,4),(2,2),(6,1)):
            words.append((condition<<28)|0x03844000|bit)
        words.extend([0xe5852000|index*8,0xe5854000|(index*8+4)])
    words.append(0xe12fff1e)
    size=len(words)*4
    for index,register,value in literals:
        offset=len(words)*4-index*4-8
        assert 0<=offset<=4095
        words[index]=0xe59f0000 | register<<12 | offset
        words.append(value)
    data,profile=simple(struct.pack('<'+'I'*len(words),*words),code_size9=size)
    profile['observe_words']=[0x02030000+i*4 for i in range(len(cases)*2)]
    return data,profile


def thumb_shifts():
    halves=[];literals=[]
    def high(op,d,n):return 0x4400 | op<<8 | (d&8)<<4 | n<<3 | (d&7)
    for register,value in ((8,8),(9,4),(10,2),(11,1),(12,8)):
        halves.extend([0x2700|value,high(2,register,7)])
    halves.append(0x2600)  # r6 = 0
    literals.append((len(halves),5,0x02030000));halves.append(0)
    for op in (2,3,4,7):  # LSL, LSR, ASR, ROR by register
        for amount in (0,1,31,32,33,255):
            literals.append((len(halves),0,0x80000001));halves.append(0)
            halves.extend([0x2100|amount,0x2e00,0x4008 | op<<6,high(2,4,6)])
            for condition,register in ((5,8),(1,9),(3,10),(7,11)):
                halves.extend([0xd000 | condition<<8,high(0,4,register)])
            halves.extend([0x6028,0x606c,high(0,5,12)])  # store result/NZCV, advance output
    halves.append(0x4770)
    size=len(halves)*2
    if len(halves)%2:halves.append(0)
    for index,register,value in literals:
        offset=len(halves)*2-((index*2+4)&~3)
        assert 0<=offset<=1020 and offset%4==0
        halves[index]=0x4800 | register<<8 | offset//4
        halves.extend([value&0xffff,value>>16])
    data,profile=simple(struct.pack('<I',0xe12fff1e),struct.pack('<'+'H'*len(halves),*halves),
                        thumb7=True,code_size7=size)
    profile['observe_words']=[0x02030000+i*4 for i in range(48)]
    return data,profile
