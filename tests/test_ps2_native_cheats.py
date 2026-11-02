"""Original data and code distinguish independent and conflicting selections."""
import os
import csv
import json
import struct
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native import cheats, profile
from tests.fixtures.ps2_native import BASE, program
from tools.qualify_ps2_runtime import executable


def test_actual_emitted_choices_execute_and_reject_tampered_original_code(tmp_path):
    emitter=os.environ.get('DECOMP_PS2_PATCHED_EMITTER');sdk=os.environ.get('DECOMP_PS2_PORT_SDK')
    if not emitter or not sdk:pytest.skip('requires the pinned runtime and built emitter')
    from decompnet.ps2_native import codegen,modules,registry,reports
    from tests.fixtures.ps2_native import i,r
    raw=bytearray(program()[0]);struct.pack_into('<4I',raw,0x100,i(9,4,2,1),i(9,2,2,2),r(8,rs=31),0)
    raw=bytes(raw);mapping=profile.module(raw)
    mapping['functions']=[dict(name='original',address=BASE,size=16)]
    mapping['code_ranges']=[dict(address=BASE,size=16)]
    policy=cheats.prepare(dict(cheats=[entry('first',BASE,i(9,4,2,10)),entry('second',BASE+4,i(9,2,2,20)),entry('data',0x200000,99)]),[(raw,mapping)])
    root=tmp_path/'source';folder=root/'game/modules/module0';folder.mkdir(parents=True);(root/'native').mkdir()
    elf=tmp_path/'input.elf';elf.write_bytes(modules.typed_elf(raw,mapping['code_ranges']))
    csv_path=tmp_path/'map.csv'
    with csv_path.open('w',newline='') as out:
        writer=csv.writer(out);writer.writerow(['Name','Start','End','Size']);writer.writerow(['original',hex(BASE),hex(BASE+16),16])
    q=lambda path:json.dumps(str(path).replace('\\','/'))
    config=tmp_path/'input.toml';config.write_text('[general]\ninput='+q(elf)+'\noutput='+q(folder)+'\nghidra_output='+q(csv_path)+'\noutput_worker_threads=1\npatch_syscalls=false\npatch_cop0=true\npatch_cache=true\n')
    def run(command,cwd,label):
        result=subprocess.run(list(map(str,command)),cwd=cwd,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        return result.stdout+result.stderr
    reports.generation_report(run([emitter,config],tmp_path,'original'),expected_functions=1)
    guards=codegen.guard_generated(folder,raw,expected_functions=1,function_ranges={BASE:16},code_ranges=mapping['code_ranges'],cheat_poll=True)
    record=registry.isolate(folder,guards);cheats.header(root,policy)
    emitted=cheats.install(root,policy,[(raw,mapping)],[record],Path(emitter),run)
    assert len(emitted)==3
    symbol=next(e['function'] for e in record['entries'] if e['address']==BASE)
    (root/'main.cpp').write_text('''#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "decomp_cheats.hpp"
#include "'''+str((folder/(record['namespace']+'.hpp')).relative_to(root)).replace('\\','/')+'''"
#include <vector>
void '''+symbol+'''(uint8_t*,R5900Context*,PS2Runtime*);
int main(){
    std::vector<uint8_t> ram(0x2000000);
    const uint32_t original[]={'''+','.join(str(w)+'u' for w in struct.unpack_from('<4I',raw,0x100))+'''};
    std::memcpy(ram.data()+'''+str(BASE)+''',original,16);
    R5900Context ctx{};
    auto execute=[&](){ctx.pc='''+str(BASE)+''';ctx.r[4]=_mm_set_epi64x(0,5);ctx.r[31]=_mm_set_epi64x(0,0x100);'''+symbol+'''(ram.data(),&ctx,nullptr);return uint32_t(_mm_cvtsi128_si32(ctx.r[2]));};
    if(execute()!=8)return 1;
    decomp_ps2_cheats::toggle(0);if(execute()!=17)return 2;
    decomp_ps2_cheats::toggle(1);if(execute()!=35)return 3;
    decomp_ps2_cheats::toggle(0);if(execute()!=26)return 4;
    decomp_ps2_cheats::toggle(1);if(execute()!=8)return 5;
    decomp_ps2_cheats::toggle(2);for(int n=0;n<256;++n)execute();
    if(ram[0x200000]!=99||std::memcmp(ram.data()+'''+str(BASE)+''',original,16))return 6;
    ram['''+str(BASE)+''']^=1;bool rejected=false;
    try{execute();}catch(const decomp_ps2::CodeMismatch&){rejected=true;}
    return rejected?0:7;
}
''')
    includes=[root/'native',Path(sdk)/'thirdparty/PS2Recomp/ps2xRuntime/include',Path(sdk)/'thirdparty/PS2Recomp/ps2xIOP/include',
              Path(sdk)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/Kernel',Path(sdk)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/vu']
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(ActualChoices LANGUAGES CXX)\nfile(GLOB_RECURSE SOURCES game/*.cpp)\nadd_executable(actual_choices main.cpp native/cheats.cpp ${SOURCES})\ntarget_compile_features(actual_choices PRIVATE cxx_std_20)\ntarget_include_directories(actual_choices PRIVATE '+' '.join(q(p) for p in includes)+')\n')
    build=tmp_path/'build'
    run(['cmake','-S',root,'-B',build],tmp_path,'configure')
    run(['cmake','--build',build,'--config','Release','--parallel','2'],tmp_path,'build')
    run([executable(build,'actual_choices')],tmp_path,'execute')


def fixture():
    raw=program()[0]
    return raw,profile.module(raw)


def entry(ident,address,value,size=4):
    return dict(id=ident,name=ident,group='Original fixture',writes=[dict(address=address,value=value,size=size)])


def test_independent_instruction_patches_combine_but_conflicting_words_do_not():
    prepared=[fixture()]
    # All four bytes of this function are valid owner-backed code. Two changes
    # target separate words; a third is an alternative to the first.
    policy=cheats.prepare(dict(cheats=[entry('a',BASE,1),entry('b',BASE+4,2),entry('c',BASE,3)]),prepared)
    group=policy['groups'][0]
    assert {v['mask'] for v in group['alternatives']}=={1,2,3,4,6}
    combined=next(v['bytes'] for v in group['alternatives'] if v['mask']==3)
    assert bytes(combined[BASE+n] for n in range(8))==b'\1\0\0\0\2\0\0\0'
    assert prepared[0][0]==program()[0]


@pytest.mark.parametrize('address,size,value',[(0x2000000,4,1),(0x100001,2,1),(0x2000,4,-1),(0x2000,1,256)])
def test_invalid_ram_operations_are_rejected(address,size,value):
    with pytest.raises(PCError,match='aligned, bounded'):
        cheats.prepare(dict(cheats=[entry('a',address,value,size)]),[fixture()])


def test_unmapped_executable_bytes_cannot_be_authorized_as_data():
    raw,mapping=fixture();mapping['functions']=mapping['functions'][1:]
    with pytest.raises(PCError,match='mapped function'):
        cheats.prepare(dict(cheats=[entry('a',BASE,1)]),[(raw,mapping)])


def test_combination_explosion_is_bounded_before_emission():
    raw,mapping=fixture()
    mapping['functions']=[dict(name='original',address=BASE,size=128)]
    with pytest.raises(PCError,match='compilation bound'):
        cheats.prepare(dict(cheats=[entry(f'c{n}',BASE+n*4,n+1) for n in range(9)]),[(raw,mapping)])


def test_native_data_application_conflicts_and_disable_leave_code_intact(tmp_path):
    if not shutil.which('cmake'):pytest.skip('requires CMake and a C++20 compiler')
    header=Path(cheats.__file__).with_name('cheat_runtime.hpp')
    shutil.copyfile(header,tmp_path/header.name)
    (tmp_path/'main.cpp').write_text(r'''
#include "cheat_runtime.hpp"
#include <array>
using namespace decomp_ps2_cheats;
int main(){
    std::vector<uint8_t> ram(0x2000000);ram[0x100000]=0x79;
    std::vector<Entry> entries={
      {"gold","Gold","Fixture",{{0x200000,17,4}},{{0,1}},{{0x100000,0,4},{0x200000,17,4}}},
      {"other","Other choice","Fixture",{{0x200000,23,4}},{{0,2}},{{0x100000,1,4},{0x200000,23,4}}},
      {"items","Items","Fixture",{{0x200004,31,2}},{},{{0x200004,31,2}}}};
    std::atomic<uint32_t> masks[1]{};
    toggle_entry(entries,masks,1,0);toggle_entry(entries,masks,1,2);
    for(int n=0;n<256;++n)poll_entries(entries,ram.data());
    uint32_t value=0;std::memcpy(&value,ram.data()+0x200000,4);
    if(value!=17||ram[0x200004]!=31||ram[0x100000]!=0x79||masks[0]!=1)return 1;
    toggle_entry(entries,masks,1,1);
    if(entries[0].enabled||!entries[1].enabled||!entries[2].enabled||masks[0]!=2)return 2;
    for(int n=0;n<256;++n)poll_entries(entries,ram.data());
    if(ram[0x200000]!=23||ram[0x100000]!=0x79)return 3;
    toggle_entry(entries,masks,1,1);ram[0x200000]=42;
    for(int n=0;n<256;++n)poll_entries(entries,ram.data());
    if(ram[0x200000]!=42||masks[0]!=0||ram[0x200004]!=31)return 4;
    return 0;
}
''')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(CheatProbe LANGUAGES CXX)\nadd_executable(cheat_probe main.cpp)\ntarget_compile_features(cheat_probe PRIVATE cxx_std_20)\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',tmp_path,'-B',build],['cmake','--build',build,'--config','Release','--parallel','2']):
        result=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([executable(build,'cheat_probe')],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
