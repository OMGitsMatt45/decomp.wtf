"""Runtime assembly selects source components and rejects altered archives."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from decompnet.pc import PCError
from decompnet.ps2_native import provider


def inputs(tmp_path, monkeypatch):
    archives = tmp_path / 'archives'; archives.mkdir()
    data = {'source/gfx/gs.cpp': b'original GS fixture\n',
            'source/game/hooks.cpp': b'title-specific fixture; must not be selected\n'}
    archive = archives / 'original.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name, contents in data.items():
            info = tarfile.TarInfo(name); info.size = len(contents); tar.addfile(info, BytesIO(contents))
    code = data['source/gfx/gs.cpp']
    expected = hashlib.sha256(b'gfx/gs.cpp\0' + hashlib.sha256(code).digest()).hexdigest()
    pins = dict(source_sha256=expected, archives=[dict(name='original',sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        copy=[dict(source='gfx',target='gfx')])])
    path = tmp_path / 'pins.json'; path.write_text(json.dumps(pins))
    monkeypatch.setattr(provider, 'INPUTS', path)
    return archives, path


def test_only_selected_runtime_source_is_published_and_changed_source_is_rejected(tmp_path, monkeypatch):
    archives, _ = inputs(tmp_path, monkeypatch)
    output = tmp_path / 'SDK with spaces'
    provider.download(output, archives=archives)
    assert [p.relative_to(output).as_posix() for p in provider.payload(output)] == ['gfx/gs.cpp']
    assert (output / 'gfx/gs.cpp').read_bytes() == b'original GS fixture\n'
    provider.verify(output)
    (output / 'gfx/gs.cpp').write_bytes(b'changed')
    with pytest.raises(PCError, match='differs'): provider.verify(output)
    with pytest.raises(PCError, match='exists'): provider.download(output, archives=archives)
    assert (output / 'gfx/gs.cpp').read_bytes() == b'changed'


def test_corrupt_archive_cannot_publish_a_partial_runtime(tmp_path, monkeypatch):
    archives, _ = inputs(tmp_path, monkeypatch)
    with (archives / 'original.tar.gz').open('ab') as out: out.write(b'changed')
    output = tmp_path / 'runtime'
    with pytest.raises(PCError, match='checksum'): provider.download(output, archives=archives)
    assert not output.exists() and not list(tmp_path.glob('.ps2-runtime-*'))


def test_assembled_identity_is_required_even_for_valid_archives(tmp_path, monkeypatch):
    archives, path = inputs(tmp_path, monkeypatch)
    pins = json.loads(path.read_text()); pins['source_sha256'] = None; path.write_text(json.dumps(pins))
    output = tmp_path / 'runtime'
    with pytest.raises(PCError, match='pinned package'): provider.download(output, archives=archives)
    assert not output.exists()
