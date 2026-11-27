"""Qualify immutable presentation intent against the pinned SDK."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from decompnet.ps2_native import presentation_patch, provider
from tools.qualify_ps2_runtime import executable


def test_prepared_picture_keeps_captured_aspect(tmp_path):
    configured = os.environ.get('DECOMP_PS2_PORT_SDK')
    if not configured:
        pytest.skip('set the pinned PS2 runtime SDK for presentation qualification')
    sdk = Path(configured)
    provider.verify(sdk)
    runtime = Path('thirdparty/PS2Recomp/ps2xRuntime')
    gfx = Path('src/gfx/backends/sdlgpu')
    stage = tmp_path / 'patched'
    inputs = [
        *(runtime / 'include/runtime/gs' / name for name in (
            'gs_types.h', 'gs_backend.h', 'gs_threaded_backend.h')),
        *(runtime / 'src/lib/gs' / name for name in (
            'gs_frontend.cpp', 'gs_threaded_backend.cpp')),
        gfx / 'sdlgpu_backend.h', gfx / 'sdlgpu_backend.cpp',
    ]
    for path in inputs:
        destination = stage / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sdk / path, destination)
    presentation_patch.patch(stage)

    fixture = Path(__file__).with_name('fixtures') / 'ps2_presentation_aspect.cpp'
    worker = stage / runtime / 'src/lib/gs/gs_threaded_backend.cpp'
    (tmp_path / 'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.24)
project(PictureAspect LANGUAGES CXX)
find_package(Threads REQUIRED)
add_executable(check_picture_aspect "{fixture.as_posix()}" "{worker.as_posix()}")
target_compile_features(check_picture_aspect PRIVATE cxx_std_20)
target_include_directories(check_picture_aspect PRIVATE
    "{(stage / runtime / 'include').as_posix()}" "{(sdk / runtime / 'include').as_posix()}")
target_link_libraries(check_picture_aspect PRIVATE Threads::Threads)
''', encoding='utf-8')
    build = tmp_path / 'build'
    for command in (['cmake', '-S', tmp_path, '-B', build],
                    ['cmake', '--build', build, '--config', 'Release', '--parallel', '2']):
        run = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
    run = subprocess.run([str(executable(build, 'check_picture_aspect'))],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
