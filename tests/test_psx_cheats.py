"""Original code/data choices, settings navigation and RAM effect checks."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from decompnet.pc import PCError
from decompnet.psx_native import cheats


def test_emitter_cache_reuses_verified_bytes_and_regenerates_corruption(tmp_path):
    from decompnet.psx_native.codegen import emit
    sdk=tmp_path/'sdk';sdk.mkdir()
    calls=[]
    def run(command,label):
        calls.append(label)
        destination=Path(command[command.index('--out-dir')+1])
        (destination/'original.c').write_text('int original(void){return 42;}\n')
        (destination/'original.h').write_text('int original(void);\n')
    for index in range(3):
        folder=tmp_path/f'output{index}';folder.mkdir()
        exe=folder/'ORIGINAL.EXE';exe.write_bytes(b'original input')
        seed=folder/'seeds.txt';seed.write_text('0x80010000\n')
        if index==2:
            next((tmp_path/'.psx-native-cache').glob('*/*/original.c')).write_text('corrupt')
        emit('emitter',exe,seed,folder,run,sdk,'original emitter')
        assert (folder/'original.c').read_text()=='int original(void){return 42;}\n'
    assert len(calls)==2


def catalog(tmp_path, body):
    path=tmp_path/'original.cht'
    path.write_text(body)
    return cheats.load(path)


def test_slide_conditional_and_extended_restore_decode(tmp_path):
    entries=catalog(tmp_path,'[Original]\nType = Gameshark\nActivation = EndFrame\n'
        '90000100 12345678\n50000304 0002\n80000110 0010\n'
        'D0000120 0070\n80000122 2400\nA7000130 10000C00\n')
    ops=entries[0]['operations']
    assert [(op['address'],op['value']) for op in ops[:4]]==[(0x100,0x12345678),(0x110,0x10),(0x114,0x12),(0x118,0x14)]
    assert ops[4]['condition']==dict(address=0x120,value=0x70)
    assert ops[5]['value']==0xc00 and ops[5]['match']==0x1000 and ops[5]['restore']


@pytest.mark.parametrize('body',[
    '[X]\n50000304 0000\n', '[X]\nD0000100 0001\n',
    '[X]\n80200000 0001\n', '[X]\n901FFFFE 12345678\n',
    '[X]\n80000100 12345678\n', '[X]\nF0000100 0001\n',
    '[X]\nType = Other\n80000100 0001\n',
])
def test_invalid_programs_fail_before_publishing(tmp_path,body):
    with pytest.raises(PCError):catalog(tmp_path,body)


def test_native_variants_follow_matching_code_and_exclusive_groups(tmp_path):
    entries=catalog(tmp_path,'[Code]\nD0010000 0001\n80010002 2400\n'
        '[Wide\\A]\nA7010008 10000C00\n[Wide\\B]\nA7010008 10000900\n'
        '[Data]\n80000100 0063\n')
    header=bytearray(2048)
    original=struct.pack('<4I',0x34020001,0,0x34031000,0)
    item=dict(image=bytes(header)+original,info=dict(load=0x80010000),boot='ORIGINAL.EXE')
    variants=list(cheats.variant_images(item,entries,[(0x10000,16)]))
    assert len(variants)==5  # (code off/on) x (wide off/A/B), except original
    assert len({v['image'] for v in variants})==5
    assert any(struct.unpack_from('<I',v['image'],2048)[0]==0x24000001 for v in variants)
    assert not any(op.get('code') for op in entries[3]['operations'])
    assert all(op.get('code') for row in entries[:3] for op in row['operations'])
    assert item['image'][2048:]==original
    # A false input-byte predicate cannot invent a variant.
    item['image']=bytes(header)+struct.pack('<4I',0x34020002,0,0x34030000,0)
    assert not list(cheats.variant_images(item,entries,[(0x10000,16)]))


HARNESS=r'''
#include "cheats.hpp"
#include "psx_runtime_menu.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
static std::array<uint8_t,0x200000> ram{};
static int started=0,mounted=1,cycles=0;
extern "C" uint32_t psx_read_word(uint32_t a){uint32_t v;std::memcpy(&v,ram.data()+(a&0x1fffff),4);return v;}
extern "C" void psx_write_byte(uint32_t a,uint8_t v){ram[a&0x1fffff]=v;}
extern "C" int psx_mod_game_started(){return started;}
extern "C" int psx_disc_tray_mounted_disc(){return mounted;}
extern "C" int psx_disc_tray_disc_count(){return 2;}
extern "C" int psx_disc_tray_cycle(int disc,int){mounted=disc;++cycles;return 0;}
int main(){
    using namespace ps1_host;
    assert(cheats.size()==4);
    cheat_set(0,true);cheat_tick();assert(cheat_read(0x100,4)==0);
    started=1;cheat_tick();assert(cheat_read(0x100,4)==0x12345678);
    cheat_disable(0);cheat_tick();assert(cheat_read(0x100,4)==0x12345678);
    cheat_write(0x120,2,0x70);cheat_write(0x122,2,0x8443);
    cheat_set(1,true);cheat_tick();assert(cheat_read(0x122,2)==0x2400);
    cheat_set(1,false);assert(cheat_read(0x122,2)==0x8443);
    cheat_write(0x130,2,0x1000);cheat_set(2,true);cheat_tick();assert(cheat_read(0x130,2)==0xc00);
    cheat_set(3,true);assert(!cheats[2].enabled&&cheat_read(0x130,2)==0x1000);
    cheat_tick();assert(cheat_read(0x130,2)==0x900);
    cheat_write(0x130,2,0xbeef);cheat_set(3,false);assert(cheat_read(0x130,2)==0xbeef);
    psx_runtime_menu_init();assert(psx_runtime_menu_open());
    psx_runtime_menu_input(PSX_MENU_ACCEPT,0);psx_runtime_menu_input(PSX_MENU_ACCEPT,0);
    assert(cheats[0].enabled);
    const uint32_t *pixels=nullptr;int w=0,h=0;
    assert(psx_runtime_menu_overlay_image(&pixels,&w,&h)&&w==800&&h==520);
    size_t light=0;for(int i=0;i<w*h;++i)if(pixels[i]==0xffedf2ff)++light;
    assert(light>100);
    psx_runtime_menu_input(PSX_MENU_BACK,0);psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_ACCEPT,0);psx_runtime_menu_input(PSX_MENU_RIGHT,0);
    psx_runtime_menu_input(PSX_MENU_DOWN,0);psx_runtime_menu_input(PSX_MENU_ACCEPT,0);
    assert(!psx_runtime_menu_is_open()&&mounted==2&&cycles==1);
    std::cout<<"Data, conditional native restoration, exclusive wide patches, settings pixels and tray changes passed\n";
}
'''


def test_actual_cpp_effects_and_settings_menu(tmp_path):
    cmake=shutil.which('cmake')
    if not cmake:pytest.skip('CMake/native compiler required for desktop effects')
    entries=catalog(tmp_path,'[Data]\n90000100 12345678\n[Code]\nD0000120 0070\n80000122 2400\n'
        '[Wide\\A]\nA7000130 10000C00\n[Wide\\B]\nA7000130 10000900\n')
    entries[1]['operations'][0]['code']=True
    (tmp_path/'game').mkdir();(tmp_path/'native').mkdir()
    cheats.emit(entries,tmp_path)
    source=Path(cheats.__file__).parent
    for name in ('cheats.hpp','menu.cpp','desktop_font.hpp'):
        shutil.copyfile(source/name,tmp_path/'native'/name)
    (tmp_path/'native/psx_runtime_menu.h').write_text('#pragma once\n#include <stdint.h>\nextern "C" {\n'
        'enum {PSX_MENU_TOGGLE,PSX_MENU_BACK,PSX_MENU_UP,PSX_MENU_DOWN,PSX_MENU_LEFT,PSX_MENU_RIGHT,PSX_MENU_ACCEPT};\n'
        'void psx_runtime_menu_init();int psx_runtime_menu_open();int psx_runtime_menu_is_open();\n'
        'void psx_runtime_menu_input(int,int);int psx_runtime_menu_insert();\n'
        'int psx_runtime_menu_overlay_image(const uint32_t**,int*,int*);\n}\n')
    (tmp_path/'native/psx_disc_tray.h').write_text('#pragma once\nextern "C" {\n'
        'enum {PSX_DISC_TRAY_OK=0,PSX_DISC_TRAY_ORIGIN_MENU=1};\n'
        'int psx_disc_tray_mounted_disc();int psx_disc_tray_disc_count();int psx_disc_tray_cycle(int,int);\n}\n')
    (tmp_path/'checks.cpp').write_text(HARNESS)
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(Ps1CheatChecks LANGUAGES CXX)\n'
        'set(CMAKE_CXX_STANDARD 17)\nadd_executable(checks checks.cpp native/menu.cpp)\n'
        'target_include_directories(checks PRIVATE native)\n'
        'if(MSVC)\n target_compile_options(checks PRIVATE /UNDEBUG)\nelse()\n target_compile_options(checks PRIVATE -UNDEBUG)\nendif()\n')
    for command in ([cmake,'-S',str(tmp_path),'-B',str(tmp_path/'build')],
                    [cmake,'--build',str(tmp_path/'build'),'--config','Release','--parallel','2']):
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stdout+result.stderr
    exe=next(path for path in (tmp_path/'build/checks',tmp_path/'build/Release/checks.exe') if path.is_file())
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_compiled_instruction_variants_execute_and_reject_stale_bytes(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned static emitter required for native execution parity')
    from decompnet.psx_native import _sdk,_recompiler,_run,codegen
    sdk=_sdk();emitter=_recompiler(sdk)
    header=bytearray(2048);header[:8]=b'PS-X EXE'
    struct.pack_into('<4I',header,0x10,0x80010000,0,0x80010000,12)
    image=bytes(header)+struct.pack('<3I',0x24020001,0x03e00008,0)
    item=dict(image=image,info=dict(load=0x80010000,entrypoint=0x80010000),boot='ORIGINAL.EXE',index=1,module_index=1)
    original=codegen.module(emitter,item,tmp_path/'original',_run,sdk)
    entries=catalog(tmp_path,'[Original instruction option]\n80010000 0009\n')
    variants=list(cheats.variant_images(item,entries,cheats.code_ranges(next((tmp_path/'original').glob('*_dispatch.c')))))
    assert len(variants)==1
    variant=dict(variants[0],module_index=2)
    modified=codegen.module(emitter,variant,tmp_path/'variant',_run,sdk)
    codegen.registry([original,modified],tmp_path/'modules.c')
    host=(Path(__file__).parent/'fixtures/psx-native/runner.c').read_text()
    host=host.replace('static size_t original_size;','unsigned char *g_psx_ram=memory;\nstatic size_t original_size;')
    (tmp_path/'runner.c').write_text(host)
    sources=[*tmp_path.glob('original/*_full_*.c'),*tmp_path.glob('original/*_dispatch.c'),
             *tmp_path.glob('variant/*_full_*.c'),*tmp_path.glob('variant/*_dispatch.c')]
    q=lambda value:json.dumps(value.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(OriginalOptions LANGUAGES C)\n'
        'set(CMAKE_C_STANDARD 11)\nadd_executable(options runner.c modules.c '+
        ' '.join(q(path.relative_to(tmp_path)) for path in sources)+')\n'
        'target_include_directories(options PRIVATE '+q(sdk/'runtime/include')+')\n'
        'target_compile_definitions(options PRIVATE PSX_NO_DEBUG_TOOLS)\n')
    _run(['cmake','-S',tmp_path,'-B',tmp_path/'build'],'Configure original instruction choices')
    _run(['cmake','--build',tmp_path/'build','--config','Release','--parallel','2'],'Compile original instruction choices')
    exe=next(path for path in (tmp_path/'build/options',tmp_path/'build/Release/options.exe') if path.is_file())
    for source,wanted in ((tmp_path/'original/ORIGINAL.EXE',1),(tmp_path/'variant/CHEAT_VARIANT.EXE',9)):
        result=json.loads(_run([exe,source,'0x80010000','0','0'],'Run guarded native choice'))
        assert result['registers'][2]==wanted and result['native_dispatches']>0 and result['cps_mode']==1
    result=json.loads(_run([exe,tmp_path/'variant/CHEAT_VARIANT.EXE','0x80010000','0','0','corrupt'],'Reject stale native choice'))
    assert result['native_rejected']


def test_identical_programs_on_distinct_discs_share_native_code(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned emitter required for source export')
    from decompnet.psx_native import export
    from .fixtures.psx_hardware import disc
    first=tmp_path/'one.iso';second=tmp_path/'two.iso'
    raw=disc(1);first.write_bytes(raw)
    changed=bytearray(raw);changed[-1]^=1;second.write_bytes(changed)
    result=export([first,second],tmp_path/'source')
    manifest=result['manifest']
    assert len(manifest['inputs'])==2 and len(manifest['code_generation'])==1
    assert [item['disc'] for item in manifest['code_generation'][0]['origins']]==[1,2]
    assert manifest['fallback']==dict(interpreter=False,runtime_compilation=False)
    root=tmp_path/'source'
    manifest_bytes=(root/'pc-project.json').read_bytes()
    subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
    subprocess.run(['git','-c','core.longpaths=true','-c','core.autocrlf=true','add','.'],cwd=root,check=True,capture_output=True)
    # Verify a complete index checkout: nested vendor rules must neither hide
    # required files nor override the output's exact-byte attributes.
    checkout=tmp_path/'checkout';checkout.mkdir()
    subprocess.run(['git','-c','core.longpaths=true','-c','core.autocrlf=true','checkout-index',
        '-a','-f','--prefix='+checkout.as_posix()+'/'],cwd=root,check=True,capture_output=True)
    assert (checkout/'pc-project.json').read_bytes()==manifest_bytes
    from decompnet import pc
    assert pc.verify(checkout)['integrity_verified']
