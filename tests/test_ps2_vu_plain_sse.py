"""Compare vectorized non-FMAC arithmetic across edges and rounding modes."""
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import pytest
from decompnet.ps2_native import vu_plain_sse
from tools.qualify_ps2_runtime import executable

def test_plain_sse_preserves_all_lane_bits_and_clip_flags(tmp_path):
    if platform.machine().lower() not in ('amd64','x86_64'):pytest.skip('SSE fixture requires an x86-64 host')
    sdk=os.environ.get('DECOMP_PS2_PORT_SDK')
    if not sdk:pytest.skip('set the pinned runtime SDK for SSE arithmetic qualification')
    if not shutil.which('cmake'):pytest.fail('SSE qualification requires CMake and C++20')
    runtime=Path(sdk)/'thirdparty/PS2Recomp/ps2xRuntime';vu=runtime/'src/lib/vu'
    folder=tmp_path/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/vu';folder.mkdir(parents=True)
    shutil.copyfile(vu/'ps2_vu1_program.h',folder/'ps2_vu1_program.h');vu_plain_sse.patch(tmp_path)
    shutil.copyfile(Path(__file__).parent/'fixtures/ps2_vu_plain_sse.cpp',tmp_path/'main.cpp')
    (tmp_path/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(VuPlainSse LANGUAGES CXX)
add_executable(plain main.cpp)
target_compile_features(plain PRIVATE cxx_std_20)
target_include_directories(plain PRIVATE "'''+folder.as_posix()+'" "'+vu.as_posix()+'" "'+(runtime/'include').as_posix()+'''" )
if(MSVC)
 target_compile_options(plain PRIVATE /O2 /fp:strict)
else()
 target_compile_options(plain PRIVATE -O2 -ffp-contract=off -frounding-math)
endif()
''')
    build=tmp_path/'build'
    for command in (['cmake','-S',tmp_path,'-B',build],['cmake','--build',build,'--config','Release','--parallel','1']):
        done=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    done=subprocess.run([str(executable(build,'plain'))],capture_output=True,text=True,timeout=60)
    assert done.returncode==0,done.stdout+done.stderr
    report=json.loads(done.stdout);print(json.dumps(report))
    assert report==dict(cases=8800000,rounding_modes=4,bit_identical=True)
