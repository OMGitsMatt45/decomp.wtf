"""Check wrapped P4 row reads and packed writes against the existing scalar GS path."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.ps2_native import graphics_p4
from tools.qualify_ps2_runtime import executable


def test_native_p4_rows_match_scalar_memory(tmp_path):
    sdk = os.environ.get("DECOMP_PS2_PORT_SDK")
    if not sdk:
        pytest.skip("set the pinned PS2 runtime SDK for GS memory qualification")
    if not shutil.which("cmake"):
        pytest.fail("GS memory qualification requires CMake and C++20")

    sdk = Path(sdk)
    runtime = Path("thirdparty/PS2Recomp/ps2xRuntime")
    memory = runtime / "src/lib/gs/ps2_gs_memory.cpp"
    header = runtime / "include/runtime/gs/ps2_gs_memory.h"
    vendor = tmp_path / "runtime"
    for name in (memory, header, Path("src/gfx/gs/gs_transfer.cpp"),
                 Path("src/gfx/backends/sdlgpu/sdlgpu_textures.cpp")):
        target = vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sdk / name, target)
    graphics_p4.patch(vendor)
    shutil.copyfile(Path(__file__).parent / "fixtures/ps2_gs_p4.cpp", tmp_path / "main.cpp")
    (tmp_path / "CMakeLists.txt").write_text(
        f'cmake_minimum_required(VERSION 3.24)\n'
        f'project(GsP4 LANGUAGES CXX)\n'
        f'add_executable(p4 main.cpp "{(vendor / memory).as_posix()}")\n'
        f'target_compile_features(p4 PRIVATE cxx_std_20)\n'
        f'target_include_directories(p4 PRIVATE "{(vendor / runtime / "include").as_posix()}"'
        f' "{(sdk / runtime / "include").as_posix()}")\n',
        encoding="utf-8",
    )
    build = tmp_path / "build"
    for command in (["cmake", "-S", tmp_path, "-B", build],
                    ["cmake", "--build", build, "--config", "Release", "--parallel", "2"]):
        result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(executable(build, "p4"))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "256 bit-exact native T4 read/write trials passed" in result.stdout
