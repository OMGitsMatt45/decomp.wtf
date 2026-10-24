"""Execute generated host code and compare original ARM code independently."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import ctypes

import pytest

from decompnet import pc
from decompnet.nds_pc import export,prepare,TranslationError
from .fixtures.nds_static import image,simple,arm_arithmetic,thumb_shifts
from decompnet.forks.scratch_dsd import crc16


def oracle(raw,profile):
    """Run the original bytes, including its real overlay-copy routine, in Unicorn.

    Both CPUs map the same host buffers, so their communication is independent of
    the generated runtime's memory and instruction implementations.
    """
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_PROT_ALL
    from unicorn.arm_const import UC_CPU_ARM_946,UC_CPU_ARM_TI925T
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_CPSR
    registers=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,
               UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,
               UC_ARM_REG_R12,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC]
    buffers={address:ctypes.create_string_buffer(size) for address,size in
             ((0x02000000,0x400000),(0x03000000,0x8000),(0x03800000,0x10000))}
    cpus=[]
    for name,header in (('arm9',0x20),('arm7',0x30)):
        machine=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        machine.ctl_set_cpu_model(UC_CPU_ARM_946 if name=='arm9' else UC_CPU_ARM_TI925T)
        for address,buffer in buffers.items():machine.mem_map_ptr(address,len(buffer),UC_PROT_ALL,ctypes.addressof(buffer))
        machine.mem_map(0xfffff000,0x1000)
        offset,entry,address,size=struct.unpack_from('<4I',raw,header)
        machine.mem_write(address,raw[offset:offset+size])
        machine.reg_write(UC_ARM_REG_PC,entry&~1)
        machine.reg_write(UC_ARM_REG_CPSR,0x10 | (0x20 if entry&1 else 0))
        machine.reg_write(UC_ARM_REG_SP,profile['processors'][name]['stack'])
        machine.reg_write(UC_ARM_REG_LR,0xfffffffc)
        cpus.append(machine)
    for _ in range(10000):
        if all(c.reg_read(UC_ARM_REG_PC)==0xfffffffc for c in cpus):break
        for c in cpus:
            pc=c.reg_read(UC_ARM_REG_PC)
            if pc==0xfffffffc:continue
            thumb=bool(c.reg_read(UC_ARM_REG_CPSR)&0x20)
            c.emu_start(pc|thumb,0xfffffffc,count=1)
    else:raise AssertionError('original fixture did not terminate')
    return dict(observed=[struct.unpack_from('<I',buffers[0x02000000],a-0x02000000)[0] for a in profile['observe_words']],
                cpus=[dict(registers=[c.reg_read(r) for r in registers],nzcv=c.reg_read(UC_ARM_REG_CPSR)&0xf0000000) for c in cpus])


def source_project(tmp_path,raw,profile):
    rom=tmp_path/'original.nds';layout=tmp_path/'reviewed.json'
    rom.write_bytes(raw);layout.write_text(json.dumps(profile))
    root=tmp_path/'Generated DS project with spaces'
    result=export(rom,layout,root)
    assert result['integrity_verified'] and not result['host_build_verified'] and not result['gameplay_verified']
    return rom,root


def build(root,rom):
    # Exported project works without decomp.wtf's Python imports or toolchains.
    extracted=subprocess.run([sys.executable,'-I',str(root/'tools/extract_assets.py'),str(rom)],capture_output=True,text=True)
    assert extracted.returncode==0,extracted.stdout+extracted.stderr
    for args in (['cmake','-S',str(root),'-B',str(root/'build'),'-DCMAKE_BUILD_TYPE=Release'],
                 ['cmake','--build',str(root/'build'),'--config','Release','--parallel','2']):
        done=subprocess.run(args,capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    return next(p for p in (root/'build/ds_static',root/'build/ds_static.exe',root/'build/Release/ds_static.exe') if p.exists())


def run(executable,root,*args,ok=True):
    result=subprocess.run([str(executable),'--assets',str(root/'assets'),*map(str,args)],capture_output=True,text=True,timeout=15)
    if ok:
        assert result.returncode==0,result.stdout+result.stderr
        return json.loads(result.stdout)
    assert result.returncode!=0
    return result.stderr


def test_original_ds_code_generates_standalone_host_repository_and_persists_save(tmp_path):
    raw,profile=image()
    rom,root=source_project(tmp_path,raw,profile)
    assert all((root/p).exists() for p in ('game/arm9.cpp','game/arm7.cpp','game/arm9_ov1.cpp','native/runtime.cpp',
                                        'CMakeLists.txt','tools/extract_assets.py','reviewed-profile.json'))
    assert not pc.status('nds')['available']  # experimental generation is explicit
    manifest=pc.verify(root)['manifest']
    assert manifest['execution_model']=='static-recompiled'
    assert manifest['fallback']==dict(interpreter=False,runtime_compilation=False)
    executable=build(root,rom)
    save=tmp_path/'game.sav'
    first=run(executable,root,'--save',save)
    reference=oracle(raw,profile)
    assert first['observed']==reference['observed']
    assert first['arm9']==reference['cpus'][0] and first['arm7']==reference['cpus'][1]
    assert first['observed']==[5,1,11,14,21,32,1]
    assert first['arm9']['registers'][0]==32 and first['arm7']['registers'][0]==11
    assert first['overlay_loads']==[1,2]
    assert save.read_bytes()==struct.pack('<I',1)
    assert run(executable,root,'--save',save)['observed'][-1]==2
    save.write_bytes(b'bad')
    assert 'save file size' in run(executable,root,'--save',save,ok=False)
    assert save.read_bytes()==b'bad'
    # A changed instruction in the owner's ROM changes generated host behavior.
    changed,reviewed=image(overlay_add=8)
    other=tmp_path/'changed';other.mkdir()
    rom2,root2=source_project(other,changed,reviewed)
    second=run(build(root2,rom2),root2)
    assert second['observed'][4]==22
    assert second['observed'][5]==33 and second['arm9']['registers'][0]==33
    assert second['observed']==oracle(changed,reviewed)['observed']
    # Rebuild a clean repository with only source and the original input.
    shutil.rmtree(root/'assets');shutil.rmtree(root/'build')
    assert run(build(root,rom),root)['observed']==[5,1,11,14,21,32,1]


def test_unsupported_instruction_and_profile_identity_fail_before_publication(tmp_path):
    raw,profile=simple(struct.pack('<I',0xef000001))  # SWI has no implemented device/service path
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(TranslationError,match='arm9 arm at 0x02000000'):
        export(rom,path,tmp_path/'output')
    assert not (tmp_path/'output').exists()
    profile['input_sha256']='0'*64
    with pytest.raises(TranslationError,match='SHA-256'):prepare(raw,profile)


def test_profile_cannot_guess_processor_modes_or_reuse_overlapping_code(tmp_path):
    raw,profile=image()
    profile['code']['arm9'][0]['mode']='thumb'
    with pytest.raises(TranslationError):prepare(raw,profile)
    raw,profile=image()
    profile['code']['arm9'].append(dict(profile['code']['arm9'][0]))
    with pytest.raises(TranslationError,match='overlapping'):prepare(raw,profile)


@pytest.mark.parametrize('case,message',[
    ('retail','secure-area ARM9'),
    ('resident-overlap','overlay overlaps resident'),
    ('constructor','constructors need execution integration'),
])
def test_unintegrated_module_layouts_fail_before_creating_output(tmp_path,case,message):
    raw,profile=image();raw=bytearray(raw)
    if case=='retail':
        raw.extend(b'\0'*0x2000)
        raw[0x4000:0x4200]=raw[0x1000:0x1200]
        struct.pack_into('<I',raw,0x20,0x4000)
    elif case=='resident-overlap':
        struct.pack_into('<I',raw,0x404,0x02000000)
        profile['code']['arm9:ov1'][0]['address']=0x02000000
    else:
        struct.pack_into('<2I',raw,0x410,0x02020000,0x02020004)
    struct.pack_into('<H',raw,0x15e,crc16(raw[:0x15e]))
    profile['input_sha256']=hashlib.sha256(raw).hexdigest()
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(TranslationError,match=message):export(rom,path,tmp_path/'output')
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('make',[arm_arithmetic,thumb_shifts],ids=['arm9-flags-shifts','arm7-thumb-shifts'])
def test_translated_integer_and_flag_semantics_match_original_cpu_execution(tmp_path,make):
    raw,profile=make()
    expected=oracle(raw,profile)
    rom,root=source_project(tmp_path,raw,profile)
    result=run(build(root,rom),root)
    assert result['observed']==expected['observed']
    assert result['arm9']==expected['cpus'][0] and result['arm7']==expected['cpus'][1]


@pytest.mark.parametrize('words,message',[
    ([0xe59f0004,0xe12fff10,0xe12fff1e,0x02040000],'untranslated ARM9'),
    ([0xe59f1004,0xe5810000,0xe12fff1e,0x02000000],'write to statically translated code'),
    ([0xeafffffe],'instruction budget exceeded'),
    ([0xe59f1004,0xe5910000,0xe12fff1e,0x04000000],'unimplemented DS memory/device'),
])
def test_unreviewed_execution_and_devices_fail_without_fallback(tmp_path,words,message):
    size=len(words)*4 if len(words)==1 else 12
    raw,profile=simple(struct.pack('<'+'I'*len(words),*words),code_size9=size)
    rom,root=source_project(tmp_path,raw,profile)
    assert message in run(build(root,rom),root,'--max-steps','100',ok=False)


def test_changed_assets_or_input_do_not_silently_change_the_translated_program(tmp_path):
    raw,profile=image()
    rom,root=source_project(tmp_path,raw,profile)
    executable=build(root,rom)
    asset=root/'assets/arm9.bin';before=asset.read_bytes()
    asset.write_bytes(bytes([before[0]^1])+before[1:])
    assert 'code differs from static translation' in run(executable,root,ok=False)
    rom.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    extraction=subprocess.run([sys.executable,'-I',str(root/'tools/extract_assets.py'),str(rom)],capture_output=True,text=True)
    assert extraction.returncode!=0 and 'SHA-256' in extraction.stderr
    assert asset.read_bytes()!=before  # failed validation did not overwrite existing assets


def test_cli_generates_only_when_experimental_mode_is_explicit(tmp_path,capsys):
    from decompnet.cli import main
    raw,profile=image()
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    output=tmp_path/'output'
    with pytest.raises(SystemExit):main(['pc','nds-generate',str(rom),str(path),str(output)])
    assert not output.exists()
    assert main(['pc','nds-generate',str(rom),str(path),str(output),'--experimental'])==0
    assert pc.verify(output)['manifest']['backend']['id']=='nds-static-experimental'
    assert not pc.status('nds')['available']


def test_existing_repository_and_input_are_preserved(tmp_path):
    raw,profile=image()
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    output=tmp_path/'output';output.mkdir();(output/'user.cpp').write_text('user changes')
    with pytest.raises(pc.PCError,match='existing work'):export(rom,path,output)
    assert (output/'user.cpp').read_text()=='user changes' and rom.read_bytes()==raw
