"""Exercise all exact keys, both units, and unknown words in native VU lookup."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from decompnet.ps2_native import vu_native
from tools.qualify_ps2_runtime import executable


def test_native_vu_lookup_exact_words_units_and_misses(tmp_path):
    if not shutil.which('cmake'):
        pytest.skip('requires CMake and a C++20 compiler')
    words=sorted({0,2**64-1,*((0x8000033c<<32)|(n*0x10001) for n in range(513))})
    vu_native.generate(SimpleNamespace(words=set(words),records=[]),tmp_path/'generated')
    (tmp_path/'generated/decomp_vu_catalog.hpp').write_text('''#pragma once
#include <cstdint>
class VU1Interpreter {};
using DecompVuFunction=bool(*)(VU1Interpreter&,uint64_t,uint32_t);
DecompVuFunction decomp_find_vu_pair(uint64_t,bool);
''')
    definitions=[];expected=[]
    for n,word in enumerate(words):
        for unit in (0,1):
            definitions.append(f'bool decomp_vu{unit}_pair{n}(VU1Interpreter&,uint64_t,uint32_t){{return {str(bool(unit)).lower()};}}')
        expected.append(f'{{{word}ull,decomp_vu0_pair{n},decomp_vu1_pair{n}}}')
    (tmp_path/'main.cpp').write_text('#include "generated/decomp_vu_catalog.hpp"\n'+ '\n'.join(definitions)+'''
struct Expected{uint64_t word;DecompVuFunction unit0,unit1;};
int main(){
    const Expected expected[]={'''+','.join(expected)+'''};
    for(const auto &e:expected){
        if(decomp_find_vu_pair(e.word,false)!=e.unit0||decomp_find_vu_pair(e.word,true)!=e.unit1)return 1;
    }
    for(uint64_t n=1;n<10000;++n)
        if(decomp_find_vu_pair(0x1234567800000000ull+n,false)||decomp_find_vu_pair(0x1234567800000000ull+n,true))return 2;
    return 0;
}
''')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(VuLookup LANGUAGES CXX)\nadd_executable(lookup main.cpp generated/catalog.cpp)\ntarget_include_directories(lookup PRIVATE generated)\ntarget_compile_features(lookup PRIVATE cxx_std_20)\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release']):
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
    subprocess.run([str(executable(build,'lookup'))],check=True,timeout=10)
