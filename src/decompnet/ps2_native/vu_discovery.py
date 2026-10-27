"""Bounded input-only discovery of VIF MPG uploads and raw VU programs.

Opcode support follows the pinned PS2Recomp compiler's GPL-3.0 definitions.
Discovery identifies candidate bytes; native dispatch still requires an exact
complete instruction-pair match, with no runtime instruction decoder fallback.
"""
import re
import struct

from ..pc import PCError

MAX_PAIRS=32768
LOWER_PRIMARY={0,1,4,5,8,9,16,17,18,19,20,21,22,23,24,26,27,28,
               32,33,36,37,40,41,44,45,46,47}
LOWER_DIRECT={0x30,0x31,0x32,0x34,0x35}
LOWER_SPECIAL={0x30,0x31,0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x3b,
               0x3c,0x3d,0x3e,0x3f,0x64,0x68,0x69,0x6c,*range(0x70,0x77),*range(0x78,0x7f)}


def supported(lower,upper):
    if upper&0x06000000:return False  # Reserved upper encoding bits.
    op=upper&63;special=(upper&3)|((upper>>4)&0x7c)
    if not (op<=0x2f or op>=0x3c and (special<=0x2a or special in (0x2c,0x2d,0x2e,0x2f,0x30))):
        return False
    if upper&0x80000000 or lower in (0,0x8000033c):return True
    op=lower>>25
    if op in LOWER_PRIMARY:return True
    if op!=0x40:return False
    direct=lower&63;special=(lower&3)|((lower>>4)&0x7c)
    return direct in LOWER_DIRECT or direct>=0x3c and special in LOWER_SPECIAL


def mpg(data,*,offset=0):
    """Complete, bounded MPG commands; preserve byte positions for evidence."""
    for match in re.finditer(b'[\x4a\xca]',data):
        at=match.start()-3
        if at<0 or (offset+at)&3:continue
        command=struct.unpack_from('<I',data,at)[0]
        count=(command>>16)&255 or 256
        if command&0xffff>=2048 or at+4+count*8>len(data):continue
        words=list(struct.iter_unpack('<II',data[at+4:at+4+count*8]))
        if all(supported(lower,upper) for lower,upper in words):
            yield dict(offset=offset+at,format='vif-mpg',words=[lower|(upper<<32) for lower,upper in words])


def raw(data):
    """Runs with at least four pairs and a complete E-bit delay pair."""
    for alignment in (0,4):
        start=alignment;run=[]
        for at in range(alignment,len(data)-7,8):
            lower,upper=struct.unpack_from('<II',data,at)
            if supported(lower,upper):
                if not run:start=at
                run.append(lower|(upper<<32))
                if len(run)>2048:run=run[-2048:];start=at-(len(run)-1)*8
                if len(run)>=4 and run[-2]&(1<<62):
                    yield dict(offset=start,format='raw-vu-program',words=list(run))
                    run=[]
            else:run=[]


class Catalog:
    def __init__(self):self.words=set();self.records=[];self._seen=set()

    def add(self,name,candidates):
        for candidate in candidates:
            identity=(name,candidate['offset'],candidate['format'])
            if identity in self._seen:continue
            self._seen.add(identity)
            self.words.update(candidate['words'])
            if len(self.words)>MAX_PAIRS:raise PCError('VU native pair catalog exceeds its export bound')
            self.records.append(dict(path=name,offset=candidate['offset'],
                format=candidate['format'],pairs=len(candidate['words'])))

    def scan(self,name,data,*,raw_programs=False):
        self.add(name,mpg(data))
        if raw_programs:self.add(name,raw(data))

    def scan_stream(self,name,read,size,*,chunk=4*1024*1024):
        if not 4096<=chunk<=32*1024*1024:raise ValueError('VU scan chunk bound differs')
        carry=b'';position=0
        while position<size:
            data=read(position,min(chunk,size-position))
            if len(data)!=min(chunk,size-position):raise PCError('truncated VU input scan: '+name)
            self.add(name,mpg(carry+data,offset=position-len(carry)))
            carry=(carry+data)[-2055:];position+=len(data)
