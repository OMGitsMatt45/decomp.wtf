"""Compare saturated FMAC retirement with ordered guest flag updates."""
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.ps2_native.vu_native import retire_saturated_fmac
from tools.qualify_ps2_runtime import executable


DRIVER = r'''
#include <cstddef>
#include <cstdint>
#include <vector>

uint32_t statusOf(uint32_t mac) {
    uint32_t result = 0;
    for (uint32_t group = 0; group < 4; ++group)
        result |= ((mac >> (4u * group)) & 15u) != 0u ? 1u << group : 0u;
    return result;
}

struct Run {
    struct PendingFlags { uint32_t issue, writes, value, sticky; };
    struct State { uint32_t mac, status, clip; } m_state;
    uint32_t m_fssetQueued;

    void ordered(const PendingFlags *head, const PendingFlags *end) {
        for (; head != end; ++head) {
            if (head->writes & 1u)
                m_state.mac = head->value;
            if (head->writes & 2u)
                m_state.status = (m_state.status & 0xFF0u) | statusOf(head->value) |
                                 (statusOf(head->value | head->sticky) << 6u);
            if (head->writes & 4u) {
                m_state.status = (m_state.status & 0x3Fu) | (head->value & 0xFC0u);
                --m_fssetQueued;
            }
            if (head->writes & 8u)
                m_state.clip = head->value;
        }
    }

    const PendingFlags *retire(const PendingFlags *head, const PendingFlags *end) {
        if (head == end)
            return end;
        // A CLIP at the end of an FMAC batch
        ordered(head, end);
        return end;
    }
};

int main() {
    uint32_t seed = 0xD008812Au;
    const auto next = [&] {
        seed ^= seed << 13u;
        seed ^= seed >> 17u;
        seed ^= seed << 5u;
        return seed;
    };
    for (uint32_t trial = 0; trial < 8192; ++trial) {
        std::vector<Run::PendingFlags> flags;
        uint32_t fssets = 0;
        const uint32_t size = 1u + next() % 128u;
        for (uint32_t issue = 0; issue < size; ++issue) {
            const uint32_t kind = next() % 8u;
            if (kind == 0u)
                continue;
            if (kind == 1u || kind == 2u) {
                if (kind == 2u)
                    flags.push_back({issue, 0u, next() & 0xFFFFFFu, 0u}); // Superseded CLIP.
                flags.push_back({issue, 8u, next() & 0xFFFFFFu, 0u});
            } else if (kind == 3u && trial % 3u == 0u) {
                flags.push_back({issue, 1u, next() & 0xFFFFu, next() & 0xFFFFu}); // FSSET cancels status.
                flags.push_back({issue, 4u, next() & 0xFC0u, 0u});
                ++fssets;
            } else {
                flags.push_back({issue, 3u, next() & 0xFFFFu, next() & 0xFFFFu});
            }
        }
        Run expected{{next() & 0xFFFFu, (next() & 0xFFFu) | (trial & 1u ? 0x3C0u : 0u),
                      next() & 0xFFFFFFu}, fssets};
        Run actual = expected;
        for (std::size_t first = 0; first < flags.size();) {
            const std::size_t last = first + 1u + next() % (flags.size() - first);
            std::size_t due = last;
            while (due < flags.size() && flags[due - 1u].issue == flags[due].issue)
                ++due; // Both writes of one issue cycle retire together.
            expected.ordered(flags.data() + first, flags.data() + due);
            if (actual.retire(flags.data() + first, flags.data() + due) != flags.data() + due ||
                actual.m_fssetQueued != expected.m_fssetQueued || actual.m_state.mac != expected.m_state.mac ||
                actual.m_state.status != expected.m_state.status || actual.m_state.clip != expected.m_state.clip)
                return 1;
            first = due;
        }
    }
}
'''


def test_saturated_flag_retirement_matches_ordered_updates(tmp_path: Path):
    if not shutil.which('cmake'):
        pytest.skip('CMake is required for the portable flag fixture')
    source = tmp_path/'main.cpp'
    source.write_text(DRIVER)
    retire_saturated_fmac(source)
    (tmp_path/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(VuFlagRetirement LANGUAGES CXX)
add_executable(vu_flags main.cpp)
target_compile_features(vu_flags PRIVATE cxx_std_20)
''')
    build = tmp_path/'build'
    for command in (
        ['cmake', '-S', tmp_path, '-B', build, '-DCMAKE_BUILD_TYPE=Release'],
        ['cmake', '--build', build, '--config', 'Release', '--parallel', '2'],
    ):
        run = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout+run.stderr
    run = subprocess.run([str(executable(build, 'vu_flags'))], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout+run.stderr
