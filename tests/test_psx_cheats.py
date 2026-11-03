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
        (destination/'ORIGINAL.EXE_full.ranges').write_text('F 80010000\nR 80010000 C\n')
    for index in range(6):
        folder=tmp_path/f'output{index}';folder.mkdir()
        exe=folder/'ORIGINAL.EXE';exe.write_bytes(b'original input')
        seed=folder/'seeds.txt';seed.write_text('0x80010000\n')
        if index==2:
            next((tmp_path/'.psx-native-cache').glob('*/*/original.c')).write_text('corrupt')
        if index==1:(folder/'ORIGINAL.EXE_full_99.c').write_text('obsolete raw shard')
        if index==4:
            metadata=next((tmp_path/'.psx-native-cache').glob('*/*/files.json'))
            legacy=json.loads(metadata.read_text())
            legacy.pop('ORIGINAL.EXE_full.ranges')
            metadata.write_text(json.dumps(legacy))
        emit('emitter',exe,seed,folder,run,sdk,'original emitter')
        assert (folder/'original.c').read_text()=='int original(void){return 42;}\n'
        assert (folder/'ORIGINAL.EXE_full.ranges').read_text()=='F 80010000\nR 80010000 C\n'
        assert not (folder/'ORIGINAL.EXE_full_99.c').exists()
    assert len(calls)==3
    # The repaired entry must be reused on the following export too.
    emit('emitter',exe,seed,folder,run,sdk,'original emitter')
    assert len(calls)==3


def test_overlay_owner_hints_recheck_bytes_after_replacement(tmp_path):
    if not shutil.which('cmake'):pytest.skip('CMake compiler required')
    from decompnet.psx_native import _run,codegen
    modules=[dict(prefix=f'decomp_m{i+1}_',entries=[0x80010000,0x80010004],
                  load_address=0x10000,image_size=8) for i in range(3)]
    codegen.registry(modules,tmp_path/'modules.c')
    (tmp_path/'cpu_state.h').write_text('''#include <stdint.h>
typedef struct {uint32_t gpr[32],pc;uint8_t(*read_byte)(uint32_t);
uint32_t(*read_word)(uint32_t);void(*write_word)(uint32_t,uint32_t);} CPUState;
''')
    declarations='\n'.join(f'''
int decomp_m{i+1}_psx_dispatch_game_compiled(CPUState*c,uint32_t a){{
if(!check({i},a))return 0;c->gpr[2]={i+100};return 1;}}
int decomp_m{i+1}_psx_game_text_native_ok(uint32_t a){{return check({i},a);}}
int decomp_m{i+1}_psx_game_text_native_ok_full(uint32_t a){{return check({i},a);}}
''' for i in range(3))
    (tmp_path/'runner.c').write_text('''#include "cpu_state.h"
#include <stdio.h>
#include <string.h>
static int selected=2,checks[3];
static int check(int i,uint32_t a){checks[i]++;return selected==i&&(a==0x80010000u||a==0x80010004u);}
int psx_dispatch_game_compiled(CPUState*,uint32_t);
int psx_game_text_native_ok(uint32_t);
int psx_game_text_native_ok_full(uint32_t);
int psx_game_is_function_entry(uint32_t);
#define CHECK(x) do{if(!(x)){fprintf(stderr,"failed line %d\\n",__LINE__);return 1;}}while(0)
'''+declarations+'''
int main(void){CPUState cpu={0};
CHECK(psx_game_text_native_ok(0x80010000u));
memset(checks,0,sizeof(checks));
CHECK(psx_dispatch_game_compiled(&cpu,0x80010000u)&&cpu.gpr[2]==102);
CHECK(checks[0]==0&&checks[1]==0&&checks[2]==1);
/* A cold neighboring entry uses the page hint, with its own guard. */
memset(checks,0,sizeof(checks));
CHECK(psx_game_text_native_ok_full(0x80010004u));
CHECK(checks[0]==1&&checks[1]==0&&checks[2]==1);
selected=1;
CHECK(psx_dispatch_game_compiled(&cpu,0x80010000u)&&cpu.gpr[2]==101);
selected=-1;cpu.gpr[2]=999;
CHECK(!psx_dispatch_game_compiled(&cpu,0x80010000u)&&cpu.gpr[2]==999);
CHECK(!psx_game_text_native_ok_full(0x80010004u));
selected=0;
CHECK(psx_dispatch_game_compiled(&cpu,0x80010004u)&&cpu.gpr[2]==100);
CHECK(psx_game_is_function_entry(0x80010000u));
memset(checks,0,sizeof(checks));
CHECK(psx_dispatch_game_compiled(&cpu,0x80010000u));
CHECK(checks[0]==1&&checks[1]==0&&checks[2]==0);
return 0;}
''')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\n'
        'project(OwnerHints LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(checks runner.c modules.c)\ntarget_include_directories(checks PRIVATE .)\n')
    _run(['cmake','-S',tmp_path,'-B',tmp_path/'build'],'Configure owner-hint guard regression')
    _run(['cmake','--build',tmp_path/'build','--config','Release','--parallel','2'],'Compile owner-hint guard regression')
    exe=next(path for path in (tmp_path/'build/checks',tmp_path/'build/Release/checks.exe') if path.is_file())
    _run([exe],'Check cached owners after code replacement')


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
#include "host_overlay.h"
#include "host_osd.h"
#include "psx_runtime_menu.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
static std::array<uint8_t,0x200000> ram{};
static int started=0,mounted=1,cycles=0;
static PsxHostVideoSettings video{1,0};
static int volume=100,hq=0;
extern "C" void psx_video_current(PsxHostVideoSettings* out){*out=video;}
extern "C" unsigned psx_video_apply_live(const PsxHostVideoSettings* next){video=*next;return 0;}
extern "C" int host_volume_get(){return volume;}
extern "C" void host_volume_set(int value){volume=value;}
extern "C" int decomp_audio_hq_enabled(){return hq;}
extern "C" int decomp_audio_hq_set(int value){hq=value;return 1;}
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
    assert(psx_runtime_menu_open());
    psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_ACCEPT,0);
    psx_runtime_menu_input(PSX_MENU_RIGHT,0);assert(video.internal_resolution==720);
    psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_LEFT,0);assert(video.texture_filter==PSX_TEXTURE_FILTER_XBR);
    psx_runtime_menu_input(PSX_MENU_RIGHT,1);assert(video.texture_filter==PSX_TEXTURE_FILTER_XBR);
    psx_runtime_menu_input(PSX_MENU_BACK,0);
    psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_ACCEPT,0);
    psx_runtime_menu_input(PSX_MENU_LEFT,0);assert(volume==95);
    psx_runtime_menu_input(PSX_MENU_DOWN,0);
    psx_runtime_menu_input(PSX_MENU_ACCEPT,0);assert(hq==1);
    psx_runtime_menu_input(PSX_MENU_RIGHT,1);assert(hq==1);
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
    (tmp_path/'native/host_overlay.h').write_text('#pragma once\n'
        '#define PSX_TEXTURE_FILTER_NEAREST 0\n#define PSX_TEXTURE_FILTER_BILINEAR 1\n#define PSX_TEXTURE_FILTER_XBR 3\n'
        'struct PsxHostVideoSettings {int internal_resolution;int texture_filter;};\n'
        'extern "C" void psx_video_current(PsxHostVideoSettings*);\n'
        'extern "C" unsigned psx_video_apply_live(const PsxHostVideoSettings*);\n')
    (tmp_path/'native/host_osd.h').write_text('#pragma once\n'
        'extern "C" int host_volume_get();extern "C" void host_volume_set(int);\n')
    (tmp_path/'native/internal_resolution.h').write_text('#pragma once\n'
        'struct Preset {int value;const char* label;};\n'
        'constexpr Preset k_psx_ir_presets[]={{1,"Native"},{720,"720p"},{-1,"Match display"}};\n'
        'constexpr int PSX_IR_PRESET_COUNT=3;\n'
        'inline const char* psx_ir_label_for(int value){for(auto preset:k_psx_ir_presets)'
        'if(preset.value==value)return preset.label;return nullptr;}\n')
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


def test_native_syscall_transfer_preserves_epc_and_resumes_after_the_trap(tmp_path):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):pytest.skip('pinned static emitter required')
    from decompnet.psx_native import _sdk,_recompiler,_run,codegen
    sdk=_sdk();emitter=_recompiler(sdk)
    header=bytearray(2048);header[:8]=b'PS-X EXE'
    struct.pack_into('<4I',header,0x10,0x80010000,0,0x80010000,16)
    image=bytes(header)+struct.pack('<4I',0x0000000c,0x2402002a,0x03e00008,0)
    item=dict(image=image,info=dict(load=0x80010000,entrypoint=0x80010000),
              boot='ORIGINAL.EXE',index=1,module_index=1)
    meta=codegen.module(emitter,item,tmp_path/'original',_run,sdk)
    assert 0x80010004 in meta['entries']
    codegen.registry([meta],tmp_path/'modules.c')
    host=(Path(__file__).parent/'fixtures/psx-native/runner.c').read_text()
    host=host.replace('static size_t original_size;','unsigned char *g_psx_ram=memory;\nstatic size_t original_size;')
    host=host.replace('/* IRQs and accelerated BIOS calls are absent in these CPU probes. */','''
int psx_syscall(CPUState*cpu,uint32_t code){(void)code;
    if(cpu->gpr[4]==1){cpu->pc=0;return 0;}
    cpu->gpr[3]=cpu->pc;cpu->pc+=4;return 1;
}
''')
    (tmp_path/'runner.c').write_text(host)
    sources=[*tmp_path.glob('original/*_full_*.c'),*tmp_path.glob('original/*_dispatch.c')]
    q=lambda value:json.dumps(value.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(TrapResume LANGUAGES C)\n'
        'set(CMAKE_C_STANDARD 11)\nadd_executable(checks runner.c modules.c '+
        ' '.join(q(path.relative_to(tmp_path)) for path in sources)+')\n'
        'target_include_directories(checks PRIVATE '+q(sdk/'runtime/include')+')\n'
        'target_compile_definitions(checks PRIVATE PSX_NO_DEBUG_TOOLS)\n')
    _run(['cmake','-S',tmp_path,'-B',tmp_path/'build'],'Configure native trap continuation')
    _run(['cmake','--build',tmp_path/'build','--config','Release','--parallel','2'],'Compile native trap continuation')
    exe=next(path for path in (tmp_path/'build/checks',tmp_path/'build/Release/checks.exe') if path.is_file())
    transfer=json.loads(_run([exe,tmp_path/'original/ORIGINAL.EXE','0x80010000','16','0'],'Run native exception transfer'))
    assert transfer['registers'][2]==42 and transfer['registers'][3]==0x80010000
    assert transfer['native_dispatches']>=2 and transfer['cps_mode']==1
    direct=json.loads(_run([exe,tmp_path/'original/ORIGINAL.EXE','0x80010000','1','0'],'Run inline syscall continuation'))
    assert direct['registers'][2]==42 and direct['registers'][3]==0


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
