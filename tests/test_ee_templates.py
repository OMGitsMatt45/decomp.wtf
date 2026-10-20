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
