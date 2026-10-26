"""Synthetic SDK interface probes matching OpenBIOS's public MIT signatures.

Recognition definitions: PCSX-Redux 55fbf046, see openbios_compat.LICENSE.
These programs contain no owner ROM bytes or proprietary SDK payload.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

from decompnet.psx_native import compatibility
from decompnet.rom import psx

BASE=0x80060000


def original(kind):
    helper=0x0c000000|(((BASE+0x100)>>2)&0x3ffffff)
    if kind=='info':
        body=[0x240a0009,0x8c42016c,0,0x20431988,helper,0xac600000,
              0x3c1f8002,0x8fff0004,0,0x03e00008,0,0,0,0,0,0]
    else:
        body=[0x8c42016c,0,0x8c4309c8,0x3c0a8005,0x254a0010,0x3c098005,
              0x25290024,0x8d480000,0,0xac4809c8,0x254a0004,0x1549fffb,
              0x24420004,helper,0,0x3c1f8002,0x8fff0004,0,0x03e00008,0]
    payload=struct.pack('<'+'I'*(len(body)+2),helper,0,*body).ljust(0x100,b'\0')
    payload+=struct.pack('<2I',0x03e00008,0)
    header=bytearray(2048);header[:8]=b'PS-X EXE'
    struct.pack_into('<4I',header,0x10,BASE+8,0,BASE,len(payload))
    image,info=psx.read_exe(bytes(header)+payload,'ORIGINAL.EXE')
    return dict(image=image,info=info,boot='ORIGINAL.EXE',index=1)


@pytest.mark.parametrize('kind,recipe',[('info','patch_card_info_1_execute'),('delay','patch_card2_2_execute')])
def test_sdk_views_are_input_derived_and_do_not_change_the_original(kind,recipe):
    item=original(kind);before=item['image']
    variants=compatibility.discover(item)
    assert len(variants)==1
    view=variants[0]
    assert view['source']['recipe']==recipe and view['info']['load']==BASE+8
    assert view['source']['original_sha256']==hashlib.sha256(before[2056:2056+len(view['image'])-2048]).hexdigest()
    assert item['image']==before
    no_link=bytearray(before);struct.pack_into('<I',no_link,2048,0)
    assert compatibility.discover(dict(item,image=bytes(no_link)))==[]
    wrong=bytearray(before);struct.pack_into('<I',wrong,2056,0x34020007)
    assert compatibility.discover(dict(item,image=bytes(wrong)))==[]


def test_patched_views_execute_like_original_bytes_including_a_delay_slot_target(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned compatibility C generation runs in the dedicated PS1 workflow')
    from decompnet.psx_native import _sdk,_recompiler,_run,codegen
    import unicorn
    from unicorn import mips_const as mips
    sdk=_sdk();compatibility.verify_profile(sdk);compiler=_recompiler(sdk)
    inputs=[];modules=[]
    for index,kind in enumerate(('info','delay')):
        item=original(kind);view=compatibility.discover(item)[0]
        # Use distinct prefixes for source-identical helpers at overlapping VMAs.
        for role,program in enumerate((item,view)):
            ordinal=len(modules)+1
            modules.append(codegen.module(compiler,dict(program,index=1,module_index=ordinal),
                                          tmp_path/f'module{ordinal}',_run,sdk))
        patched=bytearray(item['image']);offset=view['info']['load']-BASE
        patched[2048+offset:2048+offset+len(view['image'])-2048]=view['image'][2048:]
        path=tmp_path/f'actual-{kind}.exe';path.write_bytes(patched)
        inputs.append((path,bytes(patched)))
    codegen.registry(modules,tmp_path/'registry.c')
    host=(Path(__file__).parent/'fixtures/psx-native/runner.c').read_text()
    host=host.replace('static size_t original_size;',
                      'unsigned char *g_psx_ram=memory;\nstatic size_t original_size;')
    host=host.replace('memcpy(memory+0x10000,original,original_size);',
        'memcpy(memory+0x60000,original,original_size);psx_write_word(0x80020004u,0x801fff00u);')
    (tmp_path/'runner.c').write_text(host)
    sources=sorted(tmp_path.glob('module*/*_full_*.c'))+sorted(tmp_path.glob('module*/*_dispatch.c'))
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(OriginalCompat LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(native_probe runner.c registry.c '+
        ' '.join(quote(p.relative_to(tmp_path)) for p in sources)+')\n'
        'target_include_directories(native_probe PRIVATE '+quote(sdk/'runtime/include')+')\n'
        'target_compile_definitions(native_probe PRIVATE PSX_NO_DEBUG_TOOLS)\n')
    for command in (['cmake','-S',tmp_path,'-B',tmp_path/'build'],
                    ['cmake','--build',tmp_path/'build','--config','Release','--parallel','2']):
        _run(command,'Build original SDK compatibility host')
    binary=next(p for p in (tmp_path/'build/native_probe',tmp_path/'build/native_probe.exe',
                            tmp_path/'build/Release/native_probe.exe') if p.exists())
    for path,image in inputs:
        for a,b in ((0,0),(7,9),(0xffffffff,0x80000000)):
            args=list(map(str,[binary,path,hex(BASE+8),hex(a),hex(b)]))
            done=subprocess.run(args,capture_output=True,text=True,timeout=30)
            assert done.returncode==0,done.stdout+done.stderr
            actual=json.loads(done.stdout)
            cpu=unicorn.Uc(unicorn.UC_ARCH_MIPS,unicorn.UC_MODE_MIPS32|unicorn.UC_MODE_LITTLE_ENDIAN)
            cpu.mem_map(0,0x200000);cpu.mem_write(BASE&0x1fffffff,image[2048:])
            cpu.mem_write(0x20004,struct.pack('<I',0x801fff00))
            for reg,value in ((mips.UC_MIPS_REG_A0,a),(mips.UC_MIPS_REG_A1,b),(mips.UC_MIPS_REG_RA,0x801fff00)):
                cpu.reg_write(reg,value)
            cpu.emu_start(BASE+8,0x801fff00,count=1000)
            assert cpu.reg_read(mips.UC_MIPS_REG_PC)==0x801fff00
            assert actual['registers']==[cpu.reg_read(mips.UC_MIPS_REG_0+i)&0xffffffff for i in range(32)]
            assert actual['native_dispatches']>0
            tampered=subprocess.run([*args,'--tamper'],capture_output=True,text=True,timeout=30)
            assert tampered.returncode==0 and json.loads(tampered.stdout)=={'native_rejected':True}
