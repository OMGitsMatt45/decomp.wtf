"""Guard generation must reject incomplete emission before changing output."""
import shutil
import struct
import subprocess

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native.codegen import guard_generated
from decompnet.ps2_native.runtime_patch import patch_ee_float_to_word
from tests.fixtures.ps2_native import program


def emission(folder):
    declaration = 'void original(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime)'
    (folder / 'ps2_recompiled_functions.h').write_text(declaration + ';\n')
    (folder / 'original.cpp').write_text(declaration + ' {\n}\n')


def snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_partial_or_changed_emitter_abi_does_not_partially_patch_output(tmp_path):
    emission(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(PCError, match='declarations'):
        guard_generated(tmp_path, program()[0], expected_functions=2)
    assert snapshot(tmp_path) == before
    (tmp_path / 'original.cpp').write_text('void changed_abi() {}\n')
    before = snapshot(tmp_path)
    with pytest.raises(PCError, match='definitions'):
        guard_generated(tmp_path, program()[0], expected_functions=1)
    assert snapshot(tmp_path) == before


def test_guard_does_not_trust_an_executable_section_outside_its_load_mapping(tmp_path):
    emission(tmp_path)
    before = snapshot(tmp_path)
    original = bytearray(program()[0])
    section_table = struct.unpack_from('<I', original, 32)[0]
    struct.pack_into('<I', original, section_table + 40 + 12, 0x180000)
    with pytest.raises(PCError, match='load mapping'):
        guard_generated(tmp_path, original, expected_functions=1)
    assert snapshot(tmp_path) == before


def test_code_identity_is_checked_before_cheat_data_side_effects(tmp_path):
    emission(tmp_path)
    guard_generated(tmp_path,program()[0],expected_functions=1,cheat_poll=True)
    text=(tmp_path/'original.cpp').read_text()
    assert text.index('::check(rdram);')<text.index('decomp_ps2_cheats::poll(rdram);')


def test_ee_float_to_word_truncates_and_saturates(tmp_path):
    header = tmp_path / 'thirdparty/PS2Recomp/ps2xRuntime/include/ps2_runtime_macros.h'
    header.parent.mkdir(parents=True)
    header.write_text(
        '#include <bit>\n#include <cmath>\n#include <cstdint>\n'
        '#define FPU_CVT_W_S(a) ((int32_t)nearbyintf((float)(a)))\n',
        encoding='utf-8',
    )
    patch_ee_float_to_word(tmp_path)
    assert 'nearbyintf' not in header.read_text(encoding='utf-8')

    compiler = shutil.which('c++') or shutil.which('clang++')
    windows_compiler = shutil.which('clang-cl') or shutil.which('cl')
    if not (compiler or windows_compiler):
        pytest.skip('requires a C++20 compiler')
    source = tmp_path / 'conversion.cpp'
    source.write_text(
        '''#include "ps2_runtime_macros.h"
#include <cfenv>

struct Case {
    uint32_t input;
    int32_t output;
};

int main()
{
    const Case cases[] = {
        {0x3fffffffu, 1}, {0xbfffffffu, -1}, {0x80000001u, 0},
        {0x4effffffu, 2147483520}, {0xceffffffu, -2147483520},
        {0x4f000000u, INT32_MAX}, {0xcf000000u, INT32_MIN},
        {0x7f800000u, INT32_MAX}, {0xff800000u, INT32_MIN},
        {0x7fc00000u, INT32_MAX}, {0xffc00000u, INT32_MIN},
    };
    const int roundingModes[] = {FE_TONEAREST, FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO};
    for (const int mode : roundingModes) {
        if (std::fesetround(mode))
            return 1;
        for (const auto test : cases) {
            volatile float value = std::bit_cast<float>(test.input);
            if (FPU_CVT_W_S(value) != test.output)
                return 2;
        }
    }
}
''',
        encoding='utf-8',
    )
    binary = tmp_path / 'conversion.exe'
    command = (
        [compiler, '-std=c++20', '-I', str(header.parent), str(source), '-o', str(binary)]
        if compiler else
        [windows_compiler, '/nologo', '/std:c++20', '/EHsc',
         '/I' + str(header.parent), str(source), '/Fe' + str(binary)]
    )
    built = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    result = subprocess.run([str(binary)], capture_output=True, timeout=10)
    assert result.returncode == 0
