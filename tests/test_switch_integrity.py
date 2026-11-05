"""Native asset hashes match independent SHA-256 across block/chunk boundaries."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.switch_native import ROOT


@pytest.fixture(scope='module')
def checker(tmp_path_factory):
    compiler = os.environ.get('DECOMP_SWITCH_CXX')
    if not compiler and os.name != 'nt':
        compiler = shutil.which('clang++') or shutil.which('c++')
    if not compiler:
        pytest.skip('native hashing requires a configured C++20 compiler and host SDK')
    root = tmp_path_factory.mktemp('switch integrity')
    shutil.copyfile(ROOT / 'integrity.cpp', root / 'integrity.cpp')
    shutil.copyfile(ROOT.parent / 'nds_native/hash.hpp', root / 'hash.hpp')
    (root / 'layout.h').write_text('')
    (root / 'main.cpp').write_text('''extern "C" int switch_asset_matches_expected(const char*, const char*);
int main(int n, char** a) { return n == 3 ? !switch_asset_matches_expected(a[1], a[2]) : 2; }
''')
    binary = root / ('check.exe' if os.name == 'nt' else 'check')
    command = [compiler, '-std=c++20', '-O2', str(root / 'integrity.cpp'), str(root / 'main.cpp'), '-o', str(binary)]
    if os.name == 'nt':
        command.append('-lbcrypt')
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('size', [0, 1, 55, 56, 63, 64, 65, 1024 * 1024, 1024 * 1024 + 1])
def test_exact_and_changed_assets(checker, tmp_path, size):
    data = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    path = tmp_path / 'asset.bin'; path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert subprocess.run([str(checker), str(path), expected], timeout=30).returncode == 0
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]) if data else b'!')
    assert subprocess.run([str(checker), str(path), expected], timeout=30).returncode == 1


def test_missing_or_directory_assets_are_rejected(checker, tmp_path):
    expected = hashlib.sha256(b'').hexdigest()
    for path in (tmp_path / 'missing.bin', tmp_path):
        assert subprocess.run([str(checker), str(path), expected], timeout=30).returncode == 1
