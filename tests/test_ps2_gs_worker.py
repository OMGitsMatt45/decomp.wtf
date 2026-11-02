"""Demonstrate retained frame ownership, then verify prompt release after use."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from decompnet.ps2_native import gs_worker
from tools.qualify_ps2_runtime import executable


def test_consumed_preparations_release_frames_before_later_blocked_work(tmp_path):
    sdk=os.environ.get('DECOMP_PS2_PORT_SDK')
    if not sdk:pytest.skip('set the pinned PS2 runtime SDK for worker qualification')
    if not shutil.which('cmake'):pytest.fail('GS worker qualification requires CMake and C++20')
    runtime=Path(sdk)/'thirdparty/PS2Recomp/ps2xRuntime'
    source=runtime/'src/lib/gs/gs_threaded_backend.cpp'
    stage=tmp_path/'patched';patched=stage/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs/gs_threaded_backend.cpp'
    patched.parent.mkdir(parents=True);shutil.copyfile(source,patched);gs_worker.patch(stage)
    shutil.copyfile(Path(gs_worker.__file__).with_name('native_gs_worker_probe.cpp'),tmp_path/'main.cpp')
    cmake='''cmake_minimum_required(VERSION 3.24)
project(GsWorkerLifetime LANGUAGES CXX)
find_package(Threads REQUIRED)
'''
    for name,implementation in [('baseline',source),('fixed',patched)]:
        cmake+=f'add_executable({name} main.cpp "{implementation.as_posix()}")\n'
        cmake+=f'target_compile_features({name} PRIVATE cxx_std_20)\n'
        cmake+=f'target_include_directories({name} PRIVATE "{(runtime/"include").as_posix()}")\n'
        cmake+=f'target_link_libraries({name} PRIVATE Threads::Threads)\n'
    (tmp_path/'CMakeLists.txt').write_text(cmake);build=tmp_path/'build'
    for command in (['cmake','-S',tmp_path,'-B',build],['cmake','--build',build,'--config','Release','--parallel','2']):
        done=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    for name,expected in [('baseline',False),('fixed',True)]:
        done=subprocess.run([str(executable(build,name)),'released' if expected else 'retained'],capture_output=True,text=True,timeout=15)
        print(name,done.stdout.strip())
        assert done.returncode==0,done.stdout+done.stderr
        assert json.loads(done.stdout)==dict(frame_released_before_later_command_finishes=expected)
