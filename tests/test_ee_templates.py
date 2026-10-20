"""The installer reconstructs exact hosts and rejects altered inputs atomically."""
import json
from pathlib import Path
import struct

import pytest

from decompnet import ee_native


def templates(root: Path) -> dict[str, bytes]:
    manifest = dict(format=1, archive_sha256=ee_native.ARCHIVE_SHA256, tools={})
    originals = {}
    for index, name in enumerate(ee_native.PROGRAMS):
        payload = b'\x7fELF\x01\x01' + bytes([index]) * 34
        image = bytearray(552)
        image[:2] = b'MZ'
        struct.pack_into('<I', image, 60, 128)
        image[128:132] = b'PE\0\0'
        struct.pack_into('<HH', image, 132, 0x14c, 1)
        struct.pack_into('<8sIIII', image, 152, b'.eepay', len(payload), 4096, len(payload), 512)
        template = bytes(image)
        image[512:] = payload
        originals[name] = bytes(image)
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.with_name(path.name + '.exe').write_bytes(template)
        manifest['tools'][name] = dict(payload_sha256=ee_native.sha256(payload),
                                      template_sha256=ee_native.sha256(template),
                                      executable_sha256=ee_native.sha256(image))
    (root / 'host-templates.json').write_text(json.dumps(manifest))
    return originals


def test_reconstruct_exact_programs_and_driver_aliases(tmp_path):
    originals = templates(tmp_path)
    ee_native.materialize(tmp_path)
    for name, image in originals.items():
        assert (tmp_path / (name + '.exe')).read_bytes() == image
    for alias, name in ee_native.ALIASES.items():
        assert (tmp_path / (alias + '.exe')).read_bytes() == originals[name]
    assert not (tmp_path / 'host-templates.json').exists()


@pytest.mark.parametrize('altered', ['original', 'template', 'identity', 'expected-image'])
def test_corrupt_input_does_not_modify_any_host(tmp_path, altered):
    templates(tmp_path)
    final = tmp_path / ee_native.PROGRAMS[-1]
    manifest_path = tmp_path / 'host-templates.json'
    if altered in ('original', 'template'):
        path = final if altered == 'original' else final.with_name(final.name + '.exe')
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    else:
        manifest = json.loads(manifest_path.read_text())
        if altered == 'identity': manifest['archive_sha256'] = '0' * 64
        else: manifest['tools'][ee_native.PROGRAMS[-1]]['executable_sha256'] = '0' * 64
        manifest_path.write_text(json.dumps(manifest))
    before = {name: (tmp_path / (name + '.exe')).read_bytes() for name in ee_native.PROGRAMS}
    with pytest.raises(ValueError):
        ee_native.materialize(tmp_path)
    assert before == {name: (tmp_path / (name + '.exe')).read_bytes() for name in ee_native.PROGRAMS}


def test_registered_install_preserves_original_files_when_extracting_templates(tmp_path, monkeypatch):
    import tarfile
    from decompnet import toolchains, wsl
    build = tmp_path / 'build'
    build.mkdir()
    originals = templates(build)
    (build / 'host-build.json').write_text(json.dumps(dict(archive_sha256=ee_native.ARCHIVE_SHA256,
        tools={name: {} for name in ee_native.PROGRAMS})))
    (build / 'bin/runtime-sentinel.dat').write_bytes(b'preserve original archive files')
    root = tmp_path / 'managed toolchains with spaces'
    downloads = root / '.downloads'
    downloads.mkdir(parents=True)
    parts = []
    for kind, names in [('original', [*ee_native.PROGRAMS, 'bin/runtime-sentinel.dat']),
                        ('templates', [*(name + '.exe' for name in ee_native.PROGRAMS),
                                       'host-templates.json', 'host-build.json'])]:
        archive = downloads / (kind + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as output:
            for name in names: output.add(build / name, arcname=name)
        parts.append(dict(url='https://invalid.test/' + archive.name, sha256=ee_native.sha256(archive.read_bytes()),
                          platforms=['windows-x86_64'], **({'ee_host_templates': True} if kind == 'templates' else {})))
    monkeypatch.setenv('DECOMPNET_TOOLCHAINS', str(root))
    monkeypatch.delenv(toolchains.EE_NATIVE_ROOT, raising=False)
    monkeypatch.setattr(toolchains, 'current_platform', lambda: 'windows-x86_64')
    monkeypatch.setattr(toolchains, '_registry_data', lambda: {'ee-gcc-2.96': dict(name='EE fixture',
        license='GPL-2.0', source='fixture', parts=parts, windows_requires=[])})
    monkeypatch.setattr(wsl, 'status', lambda: pytest.fail('native installation used WSL'))
    monkeypatch.setattr(toolchains, '_download', lambda *a: pytest.fail('fixture should use verified cached archives'))
    destination = toolchains.install('ee-gcc-2.96', log=lambda *a: None)
    for name, image in originals.items():
        assert (destination / name).read_bytes() == (build / name).read_bytes()
        assert (destination / (name + '.exe')).read_bytes() == image
    assert (destination / 'bin/runtime-sentinel.dat').read_bytes() == b'preserve original archive files'
    assert not (destination / 'windows-host-templates').exists()
    assert toolchains.installed('ee-gcc-2.96')['platform'] == 'windows-x86_64'
