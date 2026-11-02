"""Checksum-bound sources survive Git's Windows line-ending defaults."""
import shutil
import subprocess

import pytest

from decompnet.ps2_native import _git_policy


def test_git_round_trip_preserves_export_bytes(tmp_path):
    if not shutil.which('git'):
        pytest.skip('Git is required for the cross-platform source round trip')
    source = tmp_path/'source'; source.mkdir()
    vendor=source/'runtime/vendor';(vendor/'src/runner').mkdir(parents=True)
    (vendor/'.gitignore').write_text('src/runner/\n')
    _git_policy(source)
    payload = {'game.cpp': b'first\r\nsecond\r\n',
               'runtime.cpp': b'first\nsecond\n',
               'mixed.cpp': b'first\r\nsecond\n',
               'program.bin': bytes(range(256)),
               'runtime/vendor/src/runner/required.cpp': b'runner\r\n'}
    for name, data in payload.items():
        (source/name).write_bytes(data)
    def git(*args, cwd=source):
        return subprocess.run(['git', *args], cwd=cwd, check=True,
                              capture_output=True, timeout=30)
    git('init')
    git('config', 'core.autocrlf', 'true')
    git('add', '.')
    git('-c', 'user.name=Source round trip', '-c', 'user.email=roundtrip@example.invalid',
        'commit', '-m', 'Original source bytes')
    for setting in ('true', 'false'):
        copy = tmp_path/('copy-'+setting)
        git('-c', 'core.autocrlf='+setting, 'clone', '--no-hardlinks', str(source), str(copy))
        assert {name: (copy/name).read_bytes() for name in payload} == payload
