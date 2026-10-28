"""Original display-capture/VRAM provenance checks, without retail inputs."""
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from decompnet.nds_native.capture_patch import patch
from decompnet.nds_native.foreground_patch import patch as foreground_patch
from decompnet.nds_native.obj_capture_patch import patch as obj_capture_patch
from decompnet.nds_native.scene_effects_patch import patch as scene_effects_patch
from .test_nds_native import sdk  # noqa: F401


@pytest.fixture(scope='module')
def capture_checks(tmp_path_factory,sdk):
    root=tmp_path_factory.mktemp('capture-origins')
    shutil.copytree(sdk/'runtime/include',root/'runtime/include')
    shutil.copytree(sdk/'runtime/gpu2d',root/'runtime/gpu2d')
    shutil.copytree(sdk/'runtime/gpu3d',root/'runtime/gpu3d')
    patch(root)
    foreground_patch(root)
    obj_capture_patch(root)
    scene_effects_patch(root)
    original=root/'runtime/gpu2d/tests/gpu2d_tests.cpp'
    observed=original.with_name('observed.cpp')
    # Run the same upstream colour/affine/capture references with tracking on.
    text,count=re.subn(r'dsr::Gpu2D (\w+);',r'dsr::Gpu2D \1;\1.set_capture_origin_tracking(true);',original.read_text())
    assert count>20
    # Tracking intentionally disables the ARM7 writable-page fast path. The
    # baseline still checks that API; the observed suite checks the inverse.
    text=text.replace('gpu.arm7_vram_page(kVram) != nullptr','gpu.arm7_vram_page(kVram) == nullptr')
    observed.write_text(text)
    shutil.copyfile(Path(__file__).parent/'fixtures/nds_capture_origins.cpp',root/'origins.cpp')
    (root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(capture_origins LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
add_library(gpu2d runtime/gpu2d/src/gpu2d.cpp)
target_include_directories(gpu2d PUBLIC runtime/include)
foreach(target original observed origins)
  if(target STREQUAL "origins")
    set(source origins.cpp)
  elseif(target STREQUAL "original")
    set(source runtime/gpu2d/tests/gpu2d_tests.cpp)
  else()
    set(source runtime/gpu2d/tests/observed.cpp)
  endif()
  add_executable(${target} ${source})
  target_link_libraries(${target} PRIVATE gpu2d)
  # Keep the fixture's assertions active in release builds.
  if(MSVC)
    target_compile_options(${target} PRIVATE /UNDEBUG)
  else()
    target_compile_options(${target} PRIVATE -UNDEBUG)
  endif()
endforeach()
''')
    for cmd in (['cmake','-S',str(root),'-B',str(root/'build'),'-DCMAKE_BUILD_TYPE=Release'],
                ['cmake','--build',str(root/'build'),'--config','Release','--parallel','2']):
        run=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        assert run.returncode==0,run.stdout+run.stderr
    def exe(name):
        return next(p for p in (root/'build'/name,root/'build'/(name+'.exe'),root/'build/Release'/(name+'.exe')) if p.is_file())
    return exe


def test_capture_tracks_generations_and_rejects_modified_pixels(capture_checks):
    run=subprocess.run([str(capture_checks('origins'))],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    assert run.stdout.strip().endswith('original captured-3D provenance checks passed')


def test_capture_observation_preserves_original_rendering(capture_checks):
    for mode in ('original','observed'):
        run=subprocess.run([str(capture_checks(mode))],capture_output=True,text=True,timeout=60)
        assert run.returncode==0,mode+': '+run.stdout+run.stderr
