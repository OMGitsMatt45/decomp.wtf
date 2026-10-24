"""CC0 original EE ELF: DMA a red GS triangle, then wait in a scheduled loop.

Constructed from documented instruction and GIF words; no retail code/assets.
"""
import struct

from .ps2_native import BASE,i,program


def original():
    raw=bytearray(program()[0]);data=BASE+0x800
    constants=[1,1<<9,(63<<32)|(63<<44),0]
    setup=[(0x1A,1),(0x4C,1<<16),(0x4E,1<<32),(0x47,0),
           (0x40,(63<<16)|(63<<48)),(0x18,0)]
    packet=[len(setup)|(1<<15)|(1<<60),0xE]
    for reg,value in setup:packet.extend((value,reg))
    packet.extend((3|(1<<15)|(1<<46)|(3<<47)|(2<<60),0x51))
    for x,y in ((8,8),(56,8),(8,56)):
        packet.extend((255,128<<32,(x*16)|((y*16)<<32),0))
    packet_address=data+len(constants)*8
    words=[]
    def load32(reg,value):words.extend((i(15,0,reg,value>>16),i(13,reg,reg,value)))
    load32(6,data);load32(4,0x12000000)
    for offset,index in ((0,0),(0x70,1),(0x80,2),(0x20,3)):
        words.extend((i(0x37,6,5,index*8),i(0x3F,4,5,offset)))
    load32(4,0x1000E000);load32(5,1);words.append(i(0x2B,4,5,0))
    loop=len(words)
    load32(4,0x1000A000);load32(5,packet_address);words.append(i(0x2B,4,5,0x10))
    load32(5,len(packet)//2);words.append(i(0x2B,4,5,0x20))
    load32(5,0x101);words.append(i(0x2B,4,5,0))
    # Let the EE clock advance between draws instead of issuing thousands of
    # redundant triangles before the first virtual field. The scheduler's
    # cycle checkpoints observe this original countdown loop.
    load32(7,8192);words.extend((i(9,7,7,-1),i(5,7,0,-2),0))
    words.extend((i(4,0,0,loop-len(words)-1),0))
    struct.pack_into('<'+'I'*len(words),raw,0x100,*words)
    struct.pack_into('<'+'Q'*(len(constants)+len(packet)),raw,0x100+data-BASE,*(constants+packet))
    table=struct.unpack_from('<I',raw,32)[0];symbols=struct.unpack_from('<I',raw,table+4*40+16)[0]
    struct.pack_into('<I',raw,symbols+16+8,len(words)*4)
    struct.pack_into('<I',raw,table+4*40+20,32) # null plus one exact STT_FUNC
    return bytes(raw)
