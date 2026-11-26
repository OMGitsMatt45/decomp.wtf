"""Compare batched CT32/Z32 writes with the pinned runtime's scalar pixels."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.ps2_native import graphics_ct32
from tools.qualify_ps2_runtime import executable


def test_native_ct32_z32_runs_match_scalar_memory(tmp_path):
    sdk = os.environ.get('DECOMP_PS2_PORT_SDK')
    if not sdk:
        pytest.skip('set the pinned PS2 runtime SDK for GS memory qualification')
    if not shutil.which('cmake'):
        pytest.fail('GS memory qualification requires CMake and C++20')

    sdk = Path(sdk)
    runtime = Path('thirdparty/PS2Recomp/ps2xRuntime')
    memory = runtime / 'src/lib/gs/ps2_gs_memory.cpp'
    vendor = tmp_path / 'runtime'
    (vendor / memory).parent.mkdir(parents=True)
    shutil.copyfile(sdk / memory, vendor / memory)
    graphics_ct32.patch(vendor)

    tests = Path(__file__).parent
    resources = tests.parent / 'src/decompnet/ps2_native'
    shutil.copyfile(resources / 'gs_owned_write.hpp', tmp_path / 'decomp_owned_write.hpp')
    shutil.copyfile(tests / 'fixtures/ps2_gs_ct32.cpp', tmp_path / 'main.cpp')
    graphics = sdk / 'src/gfx/gs'
    (tmp_path / 'CMakeLists.txt').write_text(
        'cmake_minimum_required(VERSION 3.24)\n'
        'project(GsCt32 LANGUAGES CXX)\n'
        'find_package(Threads REQUIRED)\n'
        f'add_executable(ct32 main.cpp "{(vendor / memory).as_posix()}"\n'
        f' "{(graphics / "gs_vram.cpp").as_posix()}" "{(graphics / "gs_transfer.cpp").as_posix()}")\n'
        'target_compile_features(ct32 PRIVATE cxx_std_20)\n'
        'target_link_libraries(ct32 PRIVATE Threads::Threads)\n'
        f'target_include_directories(ct32 PRIVATE . "{(sdk / "src").as_posix()}"'
        f' "{(sdk / runtime / "include").as_posix()}")\n',
        encoding='utf-8',
    )
    build = tmp_path / 'build'
    for command in (['cmake', '-S', tmp_path, '-B', build, '-DCMAKE_BUILD_TYPE=Release'],
                    ['cmake', '--build', build, '--config', 'Release', '--parallel', '2']):
        result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr

    result = subprocess.run([str(executable(build, 'ct32'))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '392 direct CT32/Z32 runs match full 4 MiB scalar VRAM' in result.stdout
    assert '20 owned-page writes preserve unowned VRAM' in result.stdout
    assert 'Partial pixels, padding, restart, wrap and unmapped transfer cases match' in result.stdout
