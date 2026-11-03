"""Check that the contiguous VIF1 path preserves all untouched lanes."""
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.ps2_native import vif_unpack
from tools.qualify_ps2_runtime import executable


DRIVER = r"""
uint32_t randomWord(uint32_t &state) {
    state = state * 1664525u + 1013904223u;
    return state;
}

template <size_t Lanes, typename Signed, typename Unsigned>
bool verify(bool zeroExtend) {
    constexpr size_t Width = sizeof(Signed);
    std::array<uint8_t, 16384> actual, expected;
    std::array<uint8_t, 256 * Lanes * Width> packed;
    uint32_t random = 0x357089DFu;
    for (uint32_t trial = 0; trial < 1024; ++trial) {
        for (auto &value : actual)
            value = static_cast<uint8_t>(randomWord(random) >> 24u);
        expected = actual;
        for (auto &value : packed)
            value = static_cast<uint8_t>(randomWord(random) >> 24u);

        const uint32_t address = (1023u - trial * 73u) & 1023u;
        const uint32_t count = 1u + (trial & 255u);
        for (uint32_t row = 0; row < count; ++row) {
            for (uint32_t lane = 0; lane < Lanes; ++lane) {
                const uint8_t *input = packed.data() + (row * Lanes + lane) * Width;
                uint32_t value = input[0];
                if constexpr (Width == 2u)
                    value |= uint32_t(input[1]) << 8u;
                constexpr uint32_t sign = 1u << (Width * 8u - 1u);
                if (!zeroExtend && (value & sign))
                    value -= sign * 2u;
                uint8_t *output = expected.data() + ((address + row) & 1023u) * 16u + lane * 4u;
                std::memcpy(output, &value, sizeof(value));
            }
        }
        copyPartialVif1Width<Lanes, Signed, Unsigned>(actual.data(), packed.data(), address, count, zeroExtend);
        if (actual != expected) {
            std::fprintf(stderr, "VIF1 unpack mismatch lanes=%zu width=%zu trial=%u unsigned=%d\n",
                         Lanes, Width, trial, zeroExtend);
            return false;
        }
    }
    return true;
}

int main() {
    for (bool zeroExtend : {false, true}) {
        if (!verify<2, int8_t, uint8_t>(zeroExtend) || !verify<2, int16_t, uint16_t>(zeroExtend) ||
            !verify<3, int8_t, uint8_t>(zeroExtend) || !verify<3, int16_t, uint16_t>(zeroExtend))
            return 1;
    }
}
"""


def test_partial_vif1_formats_preserve_untouched_lanes_and_wrap(tmp_path: Path):
    if not shutil.which('cmake'):
        pytest.skip('CMake is required for the portable unpack fixture')
    (tmp_path/'main.cpp').write_text(
        '#include <array>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n'
        +vif_unpack.HELPERS+DRIVER)
    (tmp_path/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(VifUnpack LANGUAGES CXX)
add_executable(vif_unpack main.cpp)
target_compile_features(vif_unpack PRIVATE cxx_std_20)
''')
    build = tmp_path/'build'
    commands = (
        ['cmake', '-S', tmp_path, '-B', build, '-DCMAKE_BUILD_TYPE=Release'],
        ['cmake', '--build', build, '--config', 'Release', '--parallel', '2'],
    )
    for command in commands:
        run = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout+run.stderr
    run = subprocess.run([str(executable(build, 'vif_unpack'))], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout+run.stderr
