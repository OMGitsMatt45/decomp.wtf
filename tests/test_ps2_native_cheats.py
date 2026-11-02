"""Original data and code distinguish independent and conflicting selections."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native import cheats, profile
from tests.fixtures.ps2_native import BASE, program
from tools.qualify_ps2_runtime import executable


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
