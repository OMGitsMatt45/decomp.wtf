"""The clang-cl driver must accept the generated vector optimization flags."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest

def test_clang_cl_accepts_both_vector_optimization_levels(tmp_path):
    if Path(os.environ.get('CXX','')).stem.lower()!='clang-cl':pytest.skip('requires the clang-cl frontend')
    if not shutil.which('cmake'):pytest.fail('compiler qualification requires CMake')
    policy=Path(__file__).parents[1]/'src/decompnet/ps2_native/NativeExecution.cmake'
    (tmp_path/'main.cpp').write_text('int vector_policy_probe(int a,int b){return a*3+b*7;}\n')
    (tmp_path/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(VuCompilerPolicy LANGUAGES CXX)
set(DECOMP_PS2_REFERENCE ON CACHE BOOL "" FORCE)
set(DECOMP_PS2_BUILD_NATIVE_TESTS OFF CACHE BOOL "" FORCE)
include("'''+policy.as_posix()+'''")
add_library(probe OBJECT main.cpp)
target_compile_options(probe PRIVATE ${_decomp_ps2_vu_options} /clang:-Werror=unused-command-line-argument)
''')
    for level in ('1','2'):
        build=tmp_path/('build'+level)
        for command in (['cmake','-S',tmp_path,'-B',build,'-DDECOMP_PS2_VU_OPTIMIZATION='+level],['cmake','--build',build,'--config','Release','--parallel','1']):
            done=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
            assert done.returncode==0,done.stdout+done.stderr
