"""Compare allocations, packet snapshots and command order in the pinned runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from decompnet.ps2_native import packet_reuse
from tools.qualify_ps2_runtime import executable

def test_packet_and_queue_reuse_preserve_bytes_and_avoid_allocations(tmp_path):
    sdk=os.environ.get('DECOMP_PS2_PORT_SDK')
    if not sdk:pytest.skip('set the pinned PS2 SDK for packet qualification')
    if not shutil.which('cmake'):pytest.fail('packet qualification requires CMake and C++20')
    sdk=Path(sdk);relative=Path('thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs')
    names=['ps2_gif_arbiter.cpp','gs_threaded_backend.cpp'];stage=tmp_path/'patched';(stage/relative).mkdir(parents=True)
    for name in names:shutil.copyfile(sdk/relative/name,stage/relative/name)
    packet_reuse.patch(stage)
    shutil.copyfile(Path(__file__).parent/'fixtures/ps2_packet_reuse.cpp',tmp_path/'main.cpp')
    includes=sdk/'thirdparty/PS2Recomp/ps2xRuntime/include'
    cmake='''cmake_minimum_required(VERSION 3.24)
project(PacketReuse LANGUAGES CXX)
find_package(Threads REQUIRED)
'''
    for target,root in [('baseline',sdk),('reused',stage)]:
        sources=' '.join('"'+(root/relative/name).as_posix()+'"' for name in names)
        cmake+=f'add_executable({target} main.cpp {sources})\n'
        cmake+=f'target_compile_features({target} PRIVATE cxx_std_20)\n'
        cmake+=f'target_include_directories({target} PRIVATE "{includes.as_posix()}")\n'
        cmake+=f'target_link_libraries({target} PRIVATE Threads::Threads)\n'
    (tmp_path/'CMakeLists.txt').write_text(cmake);build=tmp_path/'build'
    for command in (['cmake','-S',tmp_path,'-B',build,'-DCMAKE_BUILD_TYPE=Release'],['cmake','--build',build,'--config','Release','--parallel','2']):
        done=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    reports={}
    for target in ('baseline','reused'):
        done=subprocess.run([str(executable(build,target))],capture_output=True,text=True,timeout=30)
        assert done.returncode==0,done.stdout+done.stderr
        reports[target]=json.loads(done.stdout)
        assert reports[target]['gif_packets']==5003 and reports[target]['gs_commands']==5001
    print(json.dumps(reports))
    assert reports['baseline']['gif_allocations']>=5000 and reports['reused']['gif_allocations']==0
    assert reports['reused']['gs_allocated_bytes']*2<reports['baseline']['gs_allocated_bytes']
