"""Original EE byte/native comparison; no retail game or console compiler."""
from io import BytesIO
import os
from pathlib import Path
import subprocess

from elftools.elf.elffile import ELFFile
import pytest

from tests.fixtures.ps2_native import BASE, MASK64, STOP, cases, initial, program, reference
from tools.qualify_ps2_runtime import download, identity, qualify


def test_original_elf_and_independent_vectors():
    image, code, entries = program()
    elf = ELFFile(BytesIO(image))
    assert elf['e_machine'] == 'EM_MIPS' and elf['e_entry'] == BASE
    symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
    assert symbols == {'probe_' + name: address for name, address in entries.items()}
    # Literal edge results verify the oracle as well as candidate comparison.
    got = reference(code, entries['word_add'], 0x7FFFFFFF, 1, entries)
    high = initial(0, 0, entries)[2] >> 64
    assert got['registers'][2] == f'{high:016x}ffffffff80000000'
    assert int(reference(code, entries['branch_likely'], 1, 2, entries)['registers'][2], 16) & MASK64 == 9
    assert int(reference(code, entries['branch_likely'], 2, 2, entries)['registers'][2], 16) & MASK64 == 5
    for name, a, b in cases():
        assert reference(code, entries[name], a, b, entries)['pc'] == STOP


def test_preserves_existing_destinations(tmp_path):
    marker = tmp_path / 'keep.txt'; marker.write_text('existing work')
    with pytest.raises(ValueError, match='existing work'): download(tmp_path)
    with pytest.raises(ValueError, match='existing work'): qualify(tmp_path / 'absent', tmp_path)
    assert marker.read_text() == 'existing work'


@pytest.fixture(scope='module')
def candidate():
    name = os.environ.get('DECOMP_PS2_CANDIDATE_ROOT')
    if not name:
        if os.environ.get('DECOMP_REQUIRE_PS2_CANDIDATE') == '1':
            pytest.fail('required PS2 candidate source path is missing')
        pytest.skip('set DECOMP_PS2_CANDIDATE_ROOT to assess the optional GPL candidate')
    root = Path(name)
    identity(root)
    return root


def test_generated_cpp_matches_original_ee(candidate, tmp_path):
    report = qualify(candidate, tmp_path / 'PS2 assessment with spaces')
    assert len(report['checks']) == 54
    assert report['generated_cpp_files'] >= 20
    assert report['functions_recompiled'] == 19
    assert report['stubs'] == report['skipped_functions'] == report['decode_failures'] == 0
    assert report['compiler']['id'] in ('GNU', 'Clang', 'MSVC', 'AppleClang')
    assert report['qualification'] == dict(cpu=True, graphics=False, iop=False,
        vu=False, audio=False, saves=False, retail=False)
    assert report['app_backend_registered'] is False
    assert report['interpreter_fallback'] is False
    assert report['runtime_code_generation'] is False


def test_source_identity_rejects_modifications(candidate, tmp_path):
    copy = tmp_path / 'candidate copy'
    subprocess.run(['git', '-c', 'core.autocrlf=false', 'clone', '--no-hardlinks', str(candidate), str(copy)],
                   check=True, capture_output=True)
    assert identity(copy) == identity(candidate)
    license = copy / 'LICENSE'; original = license.read_bytes()
    license.write_bytes(original + b'\nchanged\n')
    with pytest.raises(ValueError, match='modified|differ'): identity(copy)
    license.write_bytes(original)
    (copy / 'unexpected.h').write_text('extra source')
    with pytest.raises(ValueError, match='extra'): identity(copy)
