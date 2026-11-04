"""Original machine code exercises loading, translation and actual host execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile

import pytest

from decompnet import pc
from decompnet.switch_native import export_probe, media, provider, sources
from tools.switch_fixture import BASE, fixture, reference


@pytest.mark.parametrize('nro,compressed', [(False, False), (False, True), (True, False)])
def test_module_layout_checksums_and_exact_identity(tmp_path, nro, compressed):
    raw = fixture(nro=nro, compressed=compressed)
    path = tmp_path / 'original module'; path.write_bytes(raw)
    result = media.load(path, include_image=True)
    assert result['input']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['entry'] == BASE and result['image_size'] == 0x3000
    assert result['format'] == ('nro' if nro else 'nso')
    assert [s['offset'] for s in result['segments']] == [0, 0x1000, 0x2000]
    assert result['image'][0x2000:] == bytes(0x1000)
    assert not result['native_game_backend_available']
    assert path.read_bytes() == raw


@pytest.mark.parametrize('change', ['checksum', 'truncated', 'memory-overlap', 'file-overlap',
    'large-image', 'bad-text', 'unknown-flags', 'wrong-magic', 'segment-range', 'bad-lz4'])
def test_invalid_input_rejected_before_tools_or_output(tmp_path, monkeypatch, change):
    raw = bytearray(fixture())
    if change == 'checksum': raw[-1] ^= 1
    elif change == 'truncated': raw = raw[:0x80]
    elif change == 'memory-overlap': struct.pack_into('<I', raw, 0x24, 4)
    elif change == 'file-overlap': struct.pack_into('<I', raw, 0x30, 0x100)
    elif change == 'large-image': struct.pack_into('<I', raw, 0x3c, 0xffffffff)
    elif change == 'bad-text': struct.pack_into('<I', raw, 0x18, 3)
    elif change == 'unknown-flags': struct.pack_into('<I', raw, 0x0c, 0x80000000)
    elif change == 'wrong-magic': raw[:4] = b'XCI0'
    elif change == 'segment-range': struct.pack_into('<I', raw, 0x20, 0xffffffff)
    elif change == 'bad-lz4': struct.pack_into('<I', raw, 0xc, 0x3f)
    path = tmp_path / 'bad.nso'; path.write_bytes(raw)
    monkeypatch.setattr(provider, 'build', lambda: pytest.fail('must validate first'))
    with pytest.raises(pc.PCError): export_probe(path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
    assert path.read_bytes() == raw


def test_lz4_overlapping_matches_and_preallocation_bounds():
    assert media.decompress(bytes([0x35]) + b'abc' + bytes([3, 0, 0x10]) + b'!', 13) == b'abcabcabcabc!'
    for packed, size in ((b'\x10a\x00\x00', 5), (b'\x10a\x05\x00', 5),
                         (b'\xf0\xff', 4), (b'\x10a', 0), (b'\x00', 5), (b'\x30ab', 3)):
        with pytest.raises(pc.PCError): media.decompress(packed, size)


def test_nro_declared_size_and_segment_overlap_are_checked(tmp_path):
    raw = bytearray(fixture(nro=True))
    struct.pack_into('<I', raw, 0x18, 0x100)
    path = tmp_path / 'bad.nro'; path.write_bytes(raw)
    with pytest.raises(pc.PCError): media.load(path)
    raw = bytearray(fixture(nro=True)); struct.pack_into('<I', raw, 0x28, 0x100)
    path.write_bytes(raw)
    with pytest.raises(pc.PCError, match='overlap'): media.load(path)


def test_cli_inspection_does_not_advertise_a_game_backend(tmp_path, capsys):
    from decompnet.cli import main
    path = tmp_path / 'fixture.nso'; path.write_bytes(fixture())
    assert main(['pc', 'switch-inspect', str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['platform'] == 'switch' and not result['native_game_backend_available']
    assert not pc.status('switch')['available']
    assert len(pc.status()['backends']) == 5


def test_existing_work_is_preserved_before_building(tmp_path, monkeypatch):
    path = tmp_path / 'original.nso'; path.write_bytes(fixture())
    dest = tmp_path / 'existing'; dest.mkdir(); (dest / 'edits.c').write_text('owner edits')
    monkeypatch.setattr(provider, 'build', lambda: pytest.fail('must preserve work first'))
    with pytest.raises(pc.PCError, match='existing work'): export_probe(path, dest)
    assert (dest / 'edits.c').read_text() == 'owner edits'


def test_vendor_pins_and_modified_vendor_rejection(tmp_path, monkeypatch):
    assert provider.verify_vendor().is_dir()
    origin = provider.ROOT
    monkeypatch.setattr(provider, 'ROOT', tmp_path)
    shutil.copyfile(origin / 'sources.json', tmp_path / 'sources.json')
    shutil.copytree(origin / 'vendor', tmp_path / 'vendor')
    file = tmp_path / 'vendor/nxport-lifter/src/insn.rs'
    file.write_text(file.read_text() + '// local change\n')
    with pytest.raises(pc.PCError, match='differs from its pin'): provider.verify_vendor()
    assert file.read_text().endswith('// local change\n')


def test_cached_donor_pull_verifies_hash_and_preserves_edits(tmp_path):
    archive = tmp_path / 'sample.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo('sample-pin/source.c'); info.size = 4
        tar.addfile(info, io.BytesIO(b'code'))
    donor = dict(id='sample', commit='a' * 40, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    assert sources.pull(tmp_path, donor)['verified']
    edited = tmp_path / 'sample/source.c'; edited.write_text('edited')
    with pytest.raises(pc.PCError, match='edits; preserved'): sources.pull(tmp_path, donor)
    assert edited.read_text() == 'edited'
    archive.write_bytes(b'corrupt')
    with pytest.raises(pc.PCError, match='checksum differs'): sources.pull(tmp_path, donor)


@pytest.fixture(scope='module')
def native_tools():
    rust = os.environ.get('DECOMP_SWITCH_RUSTC') or shutil.which('rustc')
    cc = os.environ.get('DECOMP_SWITCH_CC') or shutil.which('clang')
    cmake = os.environ.get('DECOMP_SWITCH_CMAKE') or shutil.which('cmake')
    if not cmake:
        candidate = Path(sys.executable).parent / ('cmake.exe' if os.name == 'nt' else 'cmake')
        if candidate.exists(): cmake = str(candidate)
    if not (rust and cc and cmake): pytest.skip('Switch execution requires Rust, Clang and CMake')
    return cmake, cc


@pytest.fixture(scope='module', params=['nso', 'compressed-nso', 'nro'])
def native_project(tmp_path_factory, native_tools, request):
    cmake, cc = native_tools
    root = tmp_path_factory.mktemp('switch source with spaces')
    path = root / 'original module'
    path.write_bytes(fixture(nro=request.param == 'nro', compressed=request.param == 'compressed-nso'))
    out = root / 'source'; export_probe(path, out)
    build = root / 'build'
    subprocess.run([cmake, '-S', str(out), '-B', str(build), '-DCMAKE_C_COMPILER=' + cc,
                    '-DCMAKE_BUILD_TYPE=Release'], check=True, capture_output=True, timeout=180)
    result = subprocess.run([cmake, '--build', str(build), '--config', 'Release', '--parallel', '2'],
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    binary = build / 'switch_probe'
    if os.name == 'nt': binary = next(build.rglob('switch_probe.exe'))
    return path, out, binary, root


def test_translated_calls_flags_fp_simd_memory_and_indirect_call_match_original(native_project):
    path, out, binary, root = native_project
    report = root / 'run.json'
    result = subprocess.run([str(binary), str(out / 'assets/image.bin'), str(report)], timeout=30)
    actual = json.loads(report.read_text())
    assert result.returncode == 0, actual
    assert actual['status'] == 'passed' and actual['native_function_entries'] >= 3
    expected = reference(path)
    for key in ('x', 'v', 'nzcv', 'data_hex'):
        assert actual[key] == expected[key], key
    assert actual['x'][0] == 150
    data = bytes.fromhex(actual['data_hex'])
    assert struct.unpack_from('<Q', data)[0] == 120
    assert struct.unpack_from('<I', data, 12)[0] == 1
    assert struct.unpack_from('<f', data, 16)[0] == 3.5
    assert struct.unpack_from('<4I', data, 32) == (16, 16, 16, 16)
    assert actual['interpreter_instructions'] == 0 and not actual['runtime_compilation']
    assert not actual['graphics'] and not actual['retail']
    assert pc.verify(out)['integrity_verified']


@pytest.mark.parametrize('flag,reason', [('--tamper-code', 'changed-code'), ('--missing-target', 'missing-native-target')])
def test_coverage_and_changed_code_fail_without_interpretation(native_project, flag, reason):
    path, out, binary, root = native_project
    report = root / (reason + '.json')
    result = subprocess.run([str(binary), str(out / 'assets/image.bin'), str(report), flag], timeout=30)
    actual = json.loads(report.read_text())
    assert result.returncode == 1 and actual['failure'] == reason
    assert actual['interpreter_instructions'] == 0 and not actual['runtime_compilation']


def test_changed_assets_rejected_before_any_guest_execution(native_project):
    path, out, binary, root = native_project
    wrong = root / 'modified.bin'; raw = bytearray((out / 'assets/image.bin').read_bytes()); raw[-1] ^= 1
    wrong.write_bytes(raw); report = root / 'asset-failed.json'
    result = subprocess.run([str(binary), str(wrong), str(report)], timeout=30)
    actual = json.loads(report.read_text())
    assert result.returncode == 1 and actual['failure'] == 'asset-identity-mismatch'
    assert actual['native_function_entries'] == 0
