"""Compile original checks against the patched pinned SPU, without SDL."""
from pathlib import Path
import shutil
import subprocess
import pytest
from decompnet.nds_native.audio_patch import patch
from .test_nds_native import sdk  # noqa: F401


@pytest.fixture(scope='module')
def audio_build(tmp_path_factory,sdk):
    root=tmp_path_factory.mktemp('audio')
    for name in ['runtime/include/dsr/spu.h','runtime/spu/src/spu.cpp']:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(sdk/name,target)
    patch(root)
    shutil.copyfile(sdk/'runtime/spu/tests/spu_tests.cpp',root/'hardware.cpp')
    shutil.copyfile(Path(__file__).parent/'fixtures/nds_audio_cleanup.cpp',root/'cleanup.cpp')
    (root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(AudioCleanupChecks LANGUAGES CXX)
add_library(spu runtime/spu/src/spu.cpp)
target_include_directories(spu PUBLIC runtime/include)
target_compile_features(spu PUBLIC cxx_std_20)
foreach(name hardware cleanup)
add_executable(${name} ${name}.cpp)
target_link_libraries(${name} PRIVATE spu)
if(MSVC)
target_compile_options(${name} PRIVATE /UNDEBUG)
target_link_options(${name} PRIVATE /STACK:8388608)
else()
target_compile_options(${name} PRIVATE -UNDEBUG)
endif()
endforeach()
''')
    for command in [['cmake','-S',str(root),'-B',str(root/'build')],['cmake','--build',str(root/'build'),'--config','Release','--parallel','2']]:
        run=subprocess.run(command,capture_output=True,text=True,timeout=180)
        assert run.returncode==0,run.stdout+run.stderr
    return root/'build'


@pytest.mark.parametrize('name',['hardware','cleanup'])
def test_original_hardware_and_clean_host_audio(audio_build,name):
    exe=next(p for p in [audio_build/name,audio_build/(name+'.exe'),audio_build/'Release'/(name+'.exe')] if p.is_file())
    run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    if name=='cleanup':assert 'guest capture isolation checks passed' in run.stdout
