"""Original bounded code-copy programs; no retail startup or SDK bytes."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from decompnet.nds_native.code_copies import recover
from .test_nds_native import sdk,generate,execute  # noqa: F401
from .fixtures.nds_static import simple


def program():
    base=0x02000000;destination=0x02018000;words=[];literals=[]
    def literal(register,value):
        literals.append((len(words),register,value));words.append(0)
    literal(4,0x02010000);words.append(0xe3a0504d)
    literal(6,0x04004008)
    words.extend([0xe5960000,0xe584000c,0xe3e00000,0xe5860000,0xe5960000,0xe5840010])
    literal(1,'first');literal(2,destination);words.append(0xe2823008)
    forward=len(words)
    words.extend([0xe4910004,0xe4820004,0xe1520003,0xbafffffb])
    literal(2,destination);words.extend([0xe12fff32,0xe5840000])
    literal(1,'second');literal(2,destination);words.extend([0xe2822000,0xe3a03008])
    backward=len(words)
    words.extend([0xe2533004,0xe7910003,0xe7820003,0xcafffffb,0xe12fff32,0xe5840004,0xe5845008,0xeafffffe])
    main_size=len(words)*4;first=base+len(words)*4;words.extend([0xe3a0000b,0xe12fff1e])
    second=base+len(words)*4;words.extend([0xe3a00016,0xe12fff1e])
    for index,register,value in literals:
        if value=='first':value=first
        if value=='second':value=second
        offset=(len(words)-index-2)*4
        words[index]=0xe59f0000|register<<12|offset;words.append(value)
    return struct.pack('<'+'I'*len(words),*words),main_size,forward*4,backward*4


def manifest(tmp_path,raw=None):
    raw,size,*_=program()if raw is None else raw
    path=tmp_path/'original.bin';path.write_bytes(raw)
    return dict(cpu='arm9',arch='v5te',modules=[dict(name='original',module_id=-1,base=0x02000000,image=str(path.resolve()),
        functions=[dict(addr=0x02000000,size=size,thumb=False,name='startup')],labels=[],calls=[],code_ranges=[[0x02000000,0x02000000+size]],data_ranges=[])])


def test_code_copy_proves_both_loops_and_preserves_original_image(tmp_path):
    m=manifest(tmp_path);before=Path(m['modules'][0]['image']).read_bytes()
    result=recover(m,tmp_path/'copies')
    assert len(result)==2 and {r['kind']for r in result}=={'forward-word-loop','backward-word-loop'}
    assert {r['destination']for r in result}=={0x02018000}
    assert len({r['module_id']for r in m['modules']})==3
    assert {Path(r['image']).read_bytes()for r in m['modules'][1:]}=={struct.pack('<2I',0xe3a0000b,0xe12fff1e),struct.pack('<2I',0xe3a00016,0xe12fff1e)}
    assert all(r['source_module_sha256']==hashlib.sha256(before).hexdigest()for r in result)
    assert Path(m['modules'][0]['image']).read_bytes()==before


@pytest.mark.parametrize('case',['wrong-stride','wrong-value','wrong-guard','wrong-call','uninitialized-source','non-pic'])
def test_code_copy_rejects_unproven_patterns(tmp_path,case):
    raw,size,forward,backward=program();image=bytearray(raw)
    if case=='wrong-stride':struct.pack_into('<I',image,forward,0xe4910008)
    elif case=='wrong-value':struct.pack_into('<I',image,forward+4,0xe4826004)
    elif case=='wrong-guard':struct.pack_into('<I',image,forward+12,0xcafffffb)
    elif case=='wrong-call':struct.pack_into('<I',image,forward+20,0xe12fff31)
    elif case=='uninitialized-source':
        load=struct.unpack_from('<I',image,forward-12)[0]
        struct.pack_into('<I',image,forward-12+8+(load&4095),0x02030000)
    elif case=='non-pic':struct.pack_into('<I',image,size,0xea000000)
    result=recover(manifest(tmp_path,(bytes(image),size,forward,backward)),tmp_path/'copies')
    assert len(result)==1 and result[0]['kind']=='backward-word-loop'


def test_native_runtime_selects_successive_copied_bodies_by_live_hash(tmp_path,sdk):
    def make():
        raw,size,*_=program()
        rom,profile=simple(raw,struct.pack('<I',0xeafffffe),code_size9=size)
        rom=bytearray(rom);struct.pack_into('<I',rom,0x16c,0x12345678)
        rom[0x170:0x200]=bytes([0x57])*0x90
        profile['input_sha256']=hashlib.sha256(rom).hexdigest()
        profile.pop('save_region');profile['observe_words']=[0x02010000+i*4 for i in range(5)]+[0x023fff6c,0x023fff70,0x023fffe8]
        return bytes(rom),profile
    rom,root,exe=generate(tmp_path/'p',make)
    result=execute(exe,root,'--save',tmp_path/'copy.sav')
    assert result['observed']==[11,22,77,0,0,0x12345678,0,0]
    assert result['unimplemented_io']==0
    recovery=json.loads((root/'game/recovery.json').read_text())
    assert len([r for r in recovery if 'runtime_code_copy'in r])==2


def stack_program():
    base=0x03800000;words=[];literals=[]
    def literal(reg,value):literals.append((len(words),reg,value));words.append(0)
    literal(13,0x0380f004);literal(1,'source')
    words.extend([0xe4910004,0xe50d0004,0xe5910000,0xe58d0000])
    literal(0,'tail');literal(1,0x02010020);words.append(0xe3a02063)
    literal(14,0);words.extend([0xe24d3004,0xe12fff13])
    size=len(words)*4;source=base+size;words.extend([0xe1c120b0,0xe12fff10])
    tail=base+len(words)*4;words.append(0xeafffffe)
    for index,reg,value in literals:
        value=source if value=='source' else tail if value=='tail' else value
        words[index]=0xe59f0000|reg<<12|(len(words)-index-2)*4;words.append(value)
    return struct.pack('<'+'I'*len(words),*words),size,tail


def test_two_word_stack_tail_is_qualified_on_arm7(tmp_path):
    raw,size,_=stack_program();path=tmp_path/'arm7.bin';path.write_bytes(raw)
    m=dict(cpu='arm7',arch='v4t',modules=[dict(name='original_arm7',module_id=-5,base=0x03800000,image=str(path.resolve()),functions=[dict(addr=0x03800000,size=size,thumb=False,name='entry')])])
    result=recover(m,tmp_path/'copies')
    assert len(result)==1 and result[0]['kind']=='two-word-stack-copy'
    assert result[0]['destination']==0x0380f000 and result[0]['size']==8


@pytest.mark.parametrize('mutation',['clobber','conditional-save','stack-frame'])
def test_saved_lr_return_requires_unchanged_register_and_frameless_leaf(tmp_path,sdk,mutation):
    from decompnet.nds_native import _sdk
    words=[0xe1a0c00e,0xeb000000,0xe12fff1c,0xe3a0004c,0xe12fff1e]
    if mutation=='clobber':words[3]=0xe3a0c000
    elif mutation=='conditional-save':words[0]=0x01a0c00e
    else:words[3]=0xe24dd008
    path=tmp_path/'original.bin';path.write_bytes(struct.pack('<5I',*words))
    m=dict(cpu='arm9',arch='v5te',modules=[dict(name='original',module_id=-1,base=0x02000000,image=str(path),
        functions=[dict(addr=0x02000000,size=12,thumb=False,name='caller'),dict(addr=0x0200000c,size=8,thumb=False,name='leaf')])])
    _,e,_=_sdk();e.emit_manifest(m,tmp_path/'out')
    cpp='\n'.join(p.read_text()for p in(tmp_path/'out').glob('chunk_*.cpp'))
    assert 'DSR_RET(c, c->r[12]);'not in cpp


def test_native_saved_lr_and_arm7_stack_tail(tmp_path,sdk):
    def make():
        # The inner call changes LR, while the incoming return lives in IP.
        words=[0xe59f4028,0xeb000001,0xe5840000,0xeafffffe,
               0xe1a0c00e,0xeb000001,0xe2800001,0xe12fff1c,0xe3a0004c,0xe12fff1e,
               0xe1a00000,0xe1a00000,0x02010000]
        arm9=struct.pack('<'+'I'*len(words),*words);arm7,size,tail=stack_program()
        rom,profile=simple(arm9,arm7,code_size9=16,code_size7=size)
        profile['code']['arm9'] += [dict(address=0x02000010,size=16,mode='arm'),dict(address=0x02000020,size=8,mode='arm')]
        profile['code']['arm7'].append(dict(address=tail,size=4,mode='arm'))
        profile.pop('save_region');profile['observe_words']=[0x02010000,0x02010020]
        return rom,profile
    _,root,exe=generate(tmp_path/'p',make)
    assert execute(exe,root,'--save',tmp_path/'stack.sav')['observed']==[77,99]
    cpp='\n'.join(p.read_text()for p in(root/'game/arm9').glob('chunk_*.cpp'))
    assert 'DSR_RET(c, c->r[12]);'in cpp
