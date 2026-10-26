"""Compile OpenBIOS's finite SDK compatibility rewrites before they are installed.

Hash and rewrite definitions are adapted from PCSX-Redux OpenBIOS at
55fbf0468345acfbe5512628a3be5c0cfe3f22e7 (MIT, copyright 2021 PCSX-Redux
authors). See openbios_compat.LICENSE. The BIOS still performs every runtime
service and rewrite; these extra modules only translate its resulting bytes.
"""
import hashlib
import json
import struct

from .. import pc
from ..rom import psx

MASK = 0xffc9a655
# hash: (public BIOS execute symbol, branch displacement, other cleared word)
RECIPES = {
    0x5123f82a: ('patch_card_info_1_execute',0,5),
    0x0bc81000: ('patch_card2_1_execute',9,None),
    0xc29df18f: ('patch_card2_2_execute',9,None),
    0xf803a6a6: ('patch_pad_1_execute',11,None),
    0x6dee1051: ('patch_pad_2_execute',10,None),
    0x012afc0a: ('patch_pad_3_execute',2,None),
    0xcef165ba: ('remove_ChgclrPAD_1_execute',7,None),
    0x5df8cc5d: ('remove_ChgclrPAD_2_execute',5,None),
    0xa1c49b0e: ('send_pad_1_execute',15,None),
    0x561b6ad1: ('send_pad_2_execute',12,None),
}


def patch_hash(words):
    value=0x5810d659
    for index,word in enumerate(words):
        kind=MASK>>(index*2)&3
        word&=(0xffffffff,0xffff0000,0xfc000000,0)[kind]
        word=(word^61)^(word>>16)
        word=(word+(word<<3))&0xffffffff
        word^=word>>4
        word=(word*0x27d4eb2f)&0xffffffff
        word^=word>>15
        value=((value+word)*0xb503198f)&0xffffffff
    return value


def verify_profile(sdk):
    """Bind the recipes to the already fingerprinted BIOS's actual table."""
    seeds=json.loads((sdk/'recompiler/seeds/openbios_elf_seeds.json').read_text())['seeds']
    symbols={row.get('label'):int(row['address'],16) for row in seeds}
    bios=(sdk/'bios/openbios.bin').read_bytes()
    for signature,(symbol,_,_) in RECIPES.items():
        address=symbols.get(symbol)
        if address is None or struct.pack('<II',signature,address) not in bios:
            raise pc.PCError('pinned OpenBIOS compatibility table differs: '+symbol)


def discover(item):
    data=item['image'][2048:];load=item['info']['load'];modules=[]
    for offset in range(8,len(data)-63,4):
        call=struct.unpack_from('<I',data,offset-8)[0]
        # The hook receives a guest return address. Require its original
        # JAL/JALR link site instead of interpreting resource bytes as a patcher.
        if not (call>>26==3 or call>>26==0 and call&63==9 and call>>11&31==31):
            continue
        words=struct.unpack_from('<16I',data,offset)
        if words[0]==words[1]==words[3]==0:
            continue
        signature=patch_hash(words)
        recipe=RECIPES.get(signature)
        if recipe is None:
            continue
        symbol,branch,clear=recipe
        # The patched branch can skip an earlier return. Include its target
        # and a complete final return, with a bounded input-only code view.
        minimum=offset+max(24,12+branch*4+8)
        end=next((at+8 for at in range(max(offset,minimum-8),min(offset+512,len(data))-7,4)
                  if struct.unpack_from('<I',data,at)[0]==0x03e00008),None)
        if end is None:
            continue
        body=bytearray(data[offset:end])
        for index,value in ((0,0),(1,0),(2,0x10000000|branch),(3,0)):
            struct.pack_into('<I',body,index*4,value)
        if clear is not None:
            struct.pack_into('<I',body,clear*4,0)
        address=load+offset
        header=bytearray(2048);header[:8]=b'PS-X EXE'
        struct.pack_into('<4I',header,0x10,address,item['info'].get('gp',0),address,len(body))
        image,info=psx.read_exe(bytes(header)+body,'SDK_COMPAT.EXE')
        modules.append(dict(image=image,info=info,boot=f'SDK_COMPAT_{len(modules)+1}.EXE',
            source=dict(format='openbios-compatibility',program=item['boot'],offset=offset,
                        recipe=symbol,original_sha256=hashlib.sha256(data[offset:end]).hexdigest())))
    return modules


def extend(discs):
    """Preserve inputs and reviewed mappings; append separately guarded views."""
    result=[]
    for disc in discs:
        modules=list(disc.get('modules',[]));seen={hashlib.sha256(disc['image']).digest()}
        seen.update(hashlib.sha256(item['image']).digest() for item in modules)
        for item in [disc,*modules]:
            for variant in discover(item):
                identity=hashlib.sha256(variant['image']).digest()
                if identity in seen:continue
                seen.add(identity);modules.append(variant)
        result.append(dict(disc,modules=modules))
    return result
