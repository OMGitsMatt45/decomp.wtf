"""CC0 original PS1 guest: native MMIO graphics/audio, BIOS CD reads and RAM.

No retail, BIOS or proprietary SDK code is contained in this fixture.
"""
import struct

from decompnet.psx_native.extract_assets import iso

BASE=0x80010000


class Program:
    def __init__(self):self.words=[];self.labels={};self.patches=[]
    def emit(self,*words):self.words.extend(words)
    def li(self,reg,value):self.emit(0x3c000000|(reg<<16)|((value>>16)&0xffff),0x34000000|(reg<<21)|(reg<<16)|(value&0xffff))
    def store(self,address,value,half=False):
        self.li(8,address);self.li(9,value);self.emit((0xa5000000 if half else 0xad000000)|(9<<16))
    def label(self,name):self.labels[name]=BASE+len(self.words)*4
    def address(self,reg,label):
        self.patches.append((len(self.words),'address',reg,label));self.emit(0,0)
    def bios(self,selector):self.li(9,selector);self.emit(0x0c000028,0)
    def bios_b(self,selector):self.li(9,selector);self.emit(0x0c00002c,0)
    def branch(self,op,rs,rt,label):
        self.patches.append((len(self.words),'branch',(op,rs,rt),label));self.emit(0,0)
    def call(self,label):
        self.patches.append((len(self.words),'call',0,label));self.emit(0,0)
    def finish(self):
        for at,kind,reg,name in self.patches:
            address=self.labels[name]
            if kind=='call':self.words[at]=0x0c000000|((address>>2)&0x03ffffff)
            elif kind=='branch':
                op,rs,rt=reg;offset=(address-(BASE+at*4+4))//4
                self.words[at]=(op<<26)|(rs<<21)|(rt<<16)|(offset&0xffff)
            else:
                self.words[at]=0x3c000000|(reg<<16)|(address>>16)
                self.words[at+1]=0x34000000|(reg<<21)|(reg<<16)|(address&0xffff)
        return struct.pack('<'+'I'*len(self.words),*self.words)
    def string(self,name,value):
        self.label(name);data=value.encode()+b'\0';data+=bytes(-len(data)%4)
        self.words.extend(struct.unpack('<'+'I'*(len(data)//4),data))


def executable(index=1):
    p=Program()
    # ExitCriticalSection is normally supplied by a game's CRT startup.
    # BIOS Exec enters a game with interrupts disabled; CD events need them.
    p.li(4,2);p.emit(0x0000000c,0)
    p.call('alias_start');p.call('alias_tail')
    p.store(0x80020000,index)
    for value in (0x00000000,0x03000000,0x08000001,0x05000000,0x06c60260,0x07040010):p.store(0x1f801814,value)
    for value in (0xe1000400,0xe3000000,0xe403bd3f,0xe5000000,
                  0x02004000,0,(240<<16)|320,
                  0x200000ff,0x00100010,0x00100130,0x00e00010):p.store(0x1f801810,value)
    # A looping original ADPCM block through the SPU transfer FIFO and voice 0.
    for address,value in ((0x1f801daa,0xc010),(0x1f801da6,0x0200),(0x1f801dac,4)):
        p.store(address,value,True)
    for value in (0x0700,0x7777,0x7777,0x7777,0x8888,0x8888,0x8888,0x8888):p.store(0x1f801da8,value,True)
    for address,value in ((0x1f801d80,0x3fff),(0x1f801d82,0x3fff),(0x1f801c00,0x3fff),
                          (0x1f801c02,0x3fff),(0x1f801c04,0x1000),(0x1f801c06,0x0200),
                          (0x1f801c08,0x000f),(0x1f801c0a,0),(0x1f801daa,0xc000),(0x1f801d88,1)):
        p.store(address,value,True)
    p.store(0x80020010,0xa001)
    p.address(4,'filename');p.li(5,1);p.bios(0)  # open(read)
    p.emit(0x00408021)                         # s0 = fd
    p.emit(0x02002021);p.li(5,0x80020100);p.li(6,2048);p.bios(2)
    p.li(8,0x8002000c);p.emit(0xad020000)       # returned byte count
    p.emit(0x02002021);p.bios(4)               # close
    p.store(0x80020010,0xa002)
    p.li(4,0);p.bios_b(0x4a)                 # InitCARD
    p.bios_b(0x4b)                          # StartCARD
    p.bios(0x70)                            # _bu_init
    p.store(0x80020010,0xa003)
    p.address(4,'cardname');p.li(5,1);p.bios(0)
    p.emit(0x00408021)                       # s0 = old fd
    p.branch(1,2,0,'new_card')               # bltz v0
    p.emit(0x02002021);p.li(5,0x80021000);p.li(6,2048);p.bios(2)
    p.li(8,0x80021000);p.emit(0x8d020000,0)
    p.li(8,0x80020018);p.emit(0xad020000)     # previous persistent word
    p.emit(0x02002021);p.bios(4)
    p.li(5,2);p.branch(4,0,0,'write_card')
    p.label('new_card');p.li(5,0x10202)      # create one block, write
    p.label('write_card');p.address(4,'cardname');p.bios(0)
    p.emit(0x00408021,0x02002021);p.li(5,0x80020100);p.li(6,2048);p.bios(3)
    p.li(8,0x8002001c);p.emit(0xad020000)     # bytes written
    p.emit(0x02002021);p.bios(4)
    p.store(0x80020010,0xa004)
    p.li(17,0x80020004);p.label('loop')
    p.emit(0x8e2c0000,0,0x258c0001,0xae2c0000,0x1000fffb,0)
    # Two callable entries share a tail at the same addresses on both discs.
    p.label('alias_start');p.emit(0x24020001)
    p.label('alias_tail');p.emit(0x24420002,0x03e00008,0)
    p.string('filename','cdrom:\\SAMPLE.BIN;1')
    p.string('cardname','bu00:DECOMP')
    payload=p.finish();payload+=bytes(-len(payload)%2048)
    header=bytearray(2048);header[:8]=b'PS-X EXE'
    struct.pack_into('<I',header,0x10,BASE)
    struct.pack_into('<II',header,0x18,BASE,len(payload))
    struct.pack_into('<I',header,0x30,0x801fff00)
    return bytes(header)+payload


def disc(index=1):
    # Extend the ISO made by the standard-library stager with a second file.
    # pycdlib supplies a standards-complete directory/path table for BIOS reads.
    import io
    import pycdlib
    image=pycdlib.PyCdlib();image.new(interchange_level=3,sys_ident='PLAYSTATION',vol_ident=f'ORIGINAL_DISC_{index}')
    for name,data in {'SYSTEM.CNF':b'BOOT = cdrom:\\PSX.EXE;1\r\n','PSX.EXE':executable(index),
                      'SAMPLE.BIN':struct.pack('<I',0xd0000000+index)+bytes(2048*index)}.items():
        image.add_fp(io.BytesIO(data),len(data),iso_path='/'+name+';1')
    out=io.BytesIO();image.write_fp(out);image.close();return out.getvalue()
