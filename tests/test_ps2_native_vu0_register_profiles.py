"""Qualify bounded VU0 import with small synthetic microprograms."""
from hashlib import sha256
import json
import os
from pathlib import Path
import struct

import pytest

from decompnet.ps2_native import vu_programs


LOW_NOP = 0x8000033C
UPPER_NOP = 0x000002FF
END = 0x40000000


def profile(directory, pairs):
    directory.mkdir()
    code = b''.join(struct.pack('<II', lower, upper) for lower, upper in pairs)
    (directory/'vu0-aa.code').write_bytes(code.ljust(4096, b'\0'))
    (directory/'entries.txt').write_text('aa 0\n', encoding='ascii')
    return {lower | upper << 32 for lower, upper in pairs}


def test_read_vu0_and_vu1_profiles_keep_separate_address_spaces(tmp_path):
    local = tmp_path/'capture'
    profile(local, [(LOW_NOP, UPPER_NOP)])
    images, entries = vu_programs.read_profiles([local], unit=0)
    assert len(images) == 1 and len(next(iter(images.values()))) == 4096
    assert entries == {(next(iter(images)), 0)}
    with pytest.raises(ValueError, match='VU1'):
        vu_programs.read_profiles([local])
    (local/'entries.txt').write_text('aa 1000\n', encoding='ascii')
    with pytest.raises(ValueError, match='inside the code image'):
        vu_programs.read_profiles([local], unit=0)


@pytest.fixture
def runtime():
    value = os.environ.get('DECOMP_PS2_VU0_REGISTER_RUNTIME')
    if not value:
        pytest.skip('Provide the exported PS2 runtime containing the pinned compiler')
    return Path(value)


def test_emit_complete_registration_and_exact_guard(tmp_path, runtime):
    local = tmp_path/'capture'
    code = [(0x10010001, UPPER_NOP), (LOW_NOP, UPPER_NOP | END), (LOW_NOP, UPPER_NOP)]
    known = profile(local, code)
    out = tmp_path/'registry'
    proof = vu_programs.emit_vu0_register_programs(runtime, [local], out, known)
    assert proof['routines'] == 1 and proof['pairs'] == 3 and not proof['runtime_compilation']
    source = (out/'vu0_register_0.cpp').read_text()
    assert 'std::memcmp(code + 0u, expected, sizeof(expected)) == 0' in source
    assert 'return p.end(0x0018u);' in source
    assert 'findVu0RegisterRoutine' in (out/'vu0_registry.cpp').read_text()
    with pytest.raises(ValueError, match='uncatalogued'):
        vu_programs.emit_vu0_register_programs(runtime, [local], out, {0})


@pytest.mark.parametrize('unsupported', [
    (0x02000000, UPPER_NOP),  # Store.
    (0x500007FF, UPPER_NOP),  # Back edge.
    (LOW_NOP, UPPER_NOP | 0x10000000),  # D bit.
])
def test_emit_rejects_unqualified_execution_paths(tmp_path, runtime, unsupported):
    local = tmp_path/'capture'
    known = profile(local, [unsupported, (LOW_NOP, UPPER_NOP), (LOW_NOP, UPPER_NOP | END), (LOW_NOP, UPPER_NOP)])
    with pytest.raises(ValueError):
        vu_programs.emit_vu0_register_programs(runtime, [local], tmp_path/'registry', known)

def test_sparse_guard_checks_only_reachable_instruction_words(tmp_path, runtime):
    local = tmp_path/'capture'
    ibeq = (0x28 << 25) | 5
    end = (LOW_NOP, UPPER_NOP | END)
    nop = (LOW_NOP, UPPER_NOP)
    known = profile(local, [(ibeq, UPPER_NOP), nop, end, nop, nop, nop, end, nop])
    out = tmp_path/'registry'
    proof = vu_programs.emit_vu0_register_programs(runtime, [local], out, known)
    assert proof['pairs'] == 6
    source = (out/'vu0_register_0.cpp').read_text()
    assert 'positions[] = {0u, 8u, 16u, 24u, 48u, 56u}' in source
    assert 'return matches(code, positions, expected);' in source


def test_local_install_keeps_the_vu1_registry(tmp_path, runtime):
    local = tmp_path/'capture'
    code = [(0x10010001, UPPER_NOP), (LOW_NOP, UPPER_NOP | END), (LOW_NOP, UPPER_NOP)]
    known = profile(local, code)
    project = tmp_path/'project'
    files = {
        'native/NativeExecution.cmake': 'DECOMP_PS2_NATIVE_VU0_PROGRAMS',
        'game/vu/catalog.cpp': '\n'.join(f'{{0x{word:016x}ull,decomp' for word in sorted(known)),
        'game/vu_programs/catalog.cpp': '// Original VU1 registry.\n',
    }
    pinned_compiler = 'runtime/ps2/thirdparty/PS2Recomp/tools/compile_vu_programs.py'
    files[pinned_compiler] = (runtime/'thirdparty/PS2Recomp/tools/compile_vu_programs.py').read_text()
    for name, content in files.items():
        path = project/name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding='utf-8')
    old_hashes = {name: sha256((project/name).read_bytes()).hexdigest() for name in files}
    manifest_path = project/'pc-project.json'
    manifest_path.write_text(json.dumps({
        'backend': {'id': 'ps2-ps2recomp-experimental'},
        'files': old_hashes,
        'vu_generation': {'whole_programs': {'routines': 1}},
    }), encoding='utf-8')
    record = vu_programs.install(project, [local], 32, unit=0)
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest['vu_generation'] == {'whole_programs': {'routines': 1}, 'whole_vu0_programs': record}
    assert all(manifest['files'][name] == original for name, original in old_hashes.items())
    added = {'game/vu0_programs/vu0_registry.cpp', 'game/vu0_programs/vu0_register_0.cpp'}
    assert manifest['files'].keys() - old_hashes.keys() == added
    assert all(manifest['files'][name] == sha256((project/name).read_bytes()).hexdigest() for name in added)
