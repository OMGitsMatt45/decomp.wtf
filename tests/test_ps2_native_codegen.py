"""Guard generation must reject incomplete emission before changing output."""
import struct

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native.codegen import guard_generated
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
