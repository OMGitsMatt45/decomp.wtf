"""Compare every VRAM byte after ownership-masked writes and address wrapping."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from tools.qualify_ps2_runtime import executable


def test_batched_owned_ct32_matches_per_pixel_writes(tmp_path):
    sdk=os.environ.get('DECOMP_PS2_PORT_SDK')
    if not sdk:pytest.skip('set the pinned PS2 runtime SDK for GS memory qualification')
    if not shutil.which('cmake'):pytest.fail('GS memory qualification requires CMake and C++20')
    sdk=Path(sdk);runtime=sdk/'thirdparty/PS2Recomp/ps2xRuntime'
    resources=Path(__file__).parents[1]/'src/decompnet/ps2_native'
    shutil.copyfile(resources/'gs_owned_write.hpp',tmp_path/'decomp_owned_write.hpp')
    shutil.copyfile(Path(__file__).parent/'fixtures/ps2_owned_write.cpp',tmp_path/'main.cpp')
    (tmp_path/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(GsOwnedWrite LANGUAGES CXX)
add_executable(owned main.cpp "'''+(runtime/'src/lib/gs/ps2_gs_memory.cpp').as_posix()+'''")
target_compile_features(owned PRIVATE cxx_std_20)
target_include_directories(owned PRIVATE . "'''+(sdk/'src').as_posix()+'" "'+(runtime/'include').as_posix()+'''")
if(MSVC)
 target_compile_options(owned PRIVATE /O2)
else()
 target_compile_options(owned PRIVATE -O2)
endif()
''')
    build=tmp_path/'build'
    for command in (['cmake','-S',tmp_path,'-B',build],['cmake','--build',build,'--config','Release','--parallel','2']):
        result=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([str(executable(build,'owned'))],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    print(json.dumps(report))
    assert report['cases']==240 and report['full_vram_identical']
    assert report['reference_ns']>0 and report['batched_ns']>0
