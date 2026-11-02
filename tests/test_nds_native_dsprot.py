"""Synthetic shifted pools; no game code, firmware or protected payloads."""
import struct

import pytest
import yaml

from decompnet.nds_native.dsprot import prepare


def layout(root):
    main = root/'arm9'
    overlays = root/'arm9_overlays'
    main.mkdir()
    overlays.mkdir()
    (main/'arm9.yaml').write_text('base_address: 33554432\n')
    (main/'arm9.bin').write_bytes(b'\x1e\xff\x2f\xe1')
    records = [dict(from_address=0x02100000, to_address=0x02000001, addend=0x2200),
               dict(from_address=0x02100004, to_address=0x02100008, addend=0x2200)]
    image = struct.pack('<4I', 0x02002201, 0x02102208, 0, 0)
    (overlays/'ov001.bin').write_bytes(image)
    path = overlays/'overlays.yaml'
    document = dict(overlays=[dict(id=1, base_address=0x02100000, code_size=16, bss_size=4,
        file_name='ov001.bin', dsprot=dict(unencrypted=dict(functions=[], relocations=records)))])
    path.write_text(yaml.safe_dump(document))
    return path, image


def test_native_separates_valid_resident_linker_record_without_changing_code(tmp_path):
    path, image = layout(tmp_path)
    facts = prepare(tmp_path)
    assert [(r['module_id'], r['to_address'], r['target_module']) for r in facts] == [(1, 0x02000001, 'arm9')]
    remaining = yaml.safe_load(path.read_text())['overlays'][0]['dsprot']['unencrypted']['relocations']
    assert [r['to_address'] for r in remaining] == [0x02100008]
    assert (path.parent/'ov001.bin').read_bytes() == image
    assert prepare(tmp_path) == []


@pytest.mark.parametrize('change', ['unknown_target', 'wrong_word', 'uninitialized_source', 'ambiguous_owner'])
def test_native_rejects_unproven_external_record_atomically(tmp_path, change):
    path, image = layout(tmp_path)
    document = yaml.safe_load(path.read_text())
    record = document['overlays'][0]['dsprot']['unencrypted']['relocations'][0]
    if change == 'unknown_target':
        record['to_address'] = 0x02200001
        (path.parent/'ov001.bin').write_bytes(struct.pack('<I', 0x02202201)+image[4:])
    elif change == 'wrong_word':
        (path.parent/'ov001.bin').write_bytes(b'\0'*4+image[4:])
    elif change == 'uninitialized_source':
        record['from_address'] = 0x02100010
    else:
        (tmp_path/'arm9/itcm.yaml').write_text('base_address: 33554432\n')
        (tmp_path/'arm9/itcm.bin').write_bytes(b'\0'*4)
    path.write_text(yaml.safe_dump(document))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        prepare(tmp_path)
    assert path.read_bytes() == before
