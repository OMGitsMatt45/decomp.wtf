"""Original enhanced-cartridge layouts, without retail, firmware or SDK payloads."""
import struct
import hashlib
from pathlib import Path

import pytest

from decompnet import nds_native
from decompnet.forks.scratch_dsd import crc16
from .test_ds_modules import fixture
from .test_nds_native import sdk  # noqa: F401


def enhanced(unit=2):
    raw = fixture()
    raw[0x12] = unit
    raw[0x1C] = 3
    struct.pack_into('<H', raw, 0x15E, crc16(raw[:0x15E]))
    return bytes(raw)


def test_native_enhanced_uses_ntr_mode_and_preserves_input(tmp_path):
    path = tmp_path / 'original enhanced.nds'
    raw = enhanced()
    path.write_bytes(raw)
    project = nds_native._prepare(path, input_format='decrypted')
    assert project['execution_mode'] == 'ntr'
    assert project['dsi_enhanced'] is True
    assert path.read_bytes() == raw


@pytest.mark.parametrize('unit', [1, 3, 255])
def test_native_dsi_exclusive_or_reserved_units_still_rejected(tmp_path, unit):
    path = tmp_path / 'unsupported.nds'
    path.write_bytes(enhanced(unit))
    with pytest.raises(ValueError, match='TWL|DSi'):
        nds_native._prepare(path)


def original_layout(base=0x02000000, *, static_size=0x5000, blocks=4):
    data = bytearray(static_size + blocks * 48)
    params = 0x900
    struct.pack_into('<I', data, 0x820, base + params)
    struct.pack_into('<I', data, 0x800, 0xE12FFF1E)
    source = base + static_size
    start = source + blocks * 32
    struct.pack_into('<9I', data, params, start, start + blocks * 16, source, source,
                     source + 0x100, 0, 0x05010000, 0xDEC00621, 0x2106C0DE)
    destinations = [0x01FF9000, 0x02FC0000, 0x02400000, 0x06880000]
    for index in range(blocks):
        destination = destinations[index]
        struct.pack_into('<4I', data, start - base + index * 16, destination, 32, destination + 24, 16)
        struct.pack_into('<2I', data, static_size + index * 32, 0xE3A00000 | (11 + index), 0xE12FFF1E)
    return data


def original_cartridge():
    raw = bytearray(0x20000)
    raw[:12] = b'ORIGINALTEST'
    raw[12:16] = b'ADQE'
    raw[0x12] = 2
    raw[0x1C] = 3
    image = original_layout()
    struct.pack_into('<4I', raw, 0x20, 0x4000, 0x02000800, 0x02000000, len(image))
    struct.pack_into('<4I', raw, 0x30, 0x10000, 0x02380000, 0x02380000, 0x100)
    raw[0x4000:0x4000 + len(image)] = image
    struct.pack_into('<H', raw, 0x15E, crc16(raw[:0x15E]))
    return bytes(raw)


def test_staging_rewrites_only_private_analysis_and_restores_exact_static_image(tmp_path):
    from decompnet.nds_native.enhanced import stage, restore_images
    raw = original_cartridge()
    source, target = tmp_path/'original.nds', tmp_path/'decoder.nds'
    source.write_bytes(raw)
    before = hashlib.sha256(raw).hexdigest()
    facts = stage(source, target, input_format='decrypted')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    staged = target.read_bytes()
    offset, entry, base, size = struct.unpack_from('<4I', staged, 0x20)
    assert staged[0x12] == 0 and entry == base + facts['main_size']
    assert staged[0x200:len(raw)] == raw[0x200:]
    assert staged[offset + 0x800:offset + 0x804] == raw[0x4800:0x4804]
    extracted, images = tmp_path/'extracted', tmp_path/'images'
    (extracted/'arm9').mkdir(parents=True); images.mkdir()
    analysis = staged[offset:offset + facts['main_size'] + 32]
    (extracted/'arm9/arm9.bin').write_bytes(analysis)
    (images/'arm9.bin').write_bytes(analysis)
    restore_images(extracted, images, facts)
    expected = raw[0x4000:0x4000 + facts['main_size']]
    assert (images/'arm9.bin').read_bytes() == expected
    assert (extracted/'arm9/arm9.bin').read_bytes() == expected


@pytest.mark.parametrize('mutation', ['source', 'init', 'overlap', 'unreferenced', 'ambiguous'])
def test_four_word_layout_rejects_unproven_metadata(mutation):
    from decompnet.nds_native.enhanced import layout
    image = original_layout()
    if mutation == 'source': struct.pack_into('<I', image, 0x908, 0x02005004)
    elif mutation == 'init': struct.pack_into('<I', image, 0x5088, 0x01FF9100)
    elif mutation == 'overlap': struct.pack_into('<I', image, 0x5090, 0x01FF9004)
    elif mutation == 'unreferenced': struct.pack_into('<I', image, 0x820, 0)
    else:
        image[0xA00:0xA24] = image[0x900:0x924]
        struct.pack_into('<I', image, 0x824, 0x02000A00)
    with pytest.raises(ValueError, match='validated referenced'):
        layout(image, 0x02000000)


def test_arm7_sdk5_descriptors_keep_constructor_word_separate_from_bss(tmp_path, sdk):
    from decompnet.nds_native.enhanced import install_arm7
    sdk_root, emitter, reader = nds_native._sdk()
    analyzer = nds_native._tool(sdk_root, 'arm7_analyze')
    image = original_layout(0x02380000, blocks=2)
    install_arm7(analyzer); install_arm7(analyzer)
    value = analyzer.parse_autoload_layout(image, 0x02380000)
    assert len(value.blocks) == 2
    assert [block.bss_size for block in value.blocks] == [16, 16]
    assert [block.destination for block in value.blocks] == [0x01FF9000, 0x02FC0000]
    assert value.blocks[0].source_bytes[:8] == struct.pack('<2I', 0xE3A0000B, 0xE12FFF1E)


def test_enhanced_helper_changes_backend_revision(monkeypatch):
    original = nds_native._source
    before = nds_native.revision()
    monkeypatch.setattr(nds_native, '_source', lambda name: original(name) + ('\n# change\n' if name == 'enhanced.py' else ''))
    assert nds_native.revision() != before


def test_dtcm_base_requires_the_declared_literal_register_and_cp15_field():
    from decompnet.nds_native.enhanced import dtcm_base
    raw = bytearray(0x40)
    struct.pack_into('<4I', raw, 0, 0xE59F2018, 0xE382200A, 0xEE092F11, 0xE12FFF1E)
    struct.pack_into('<I', raw, 0x20, 0x02E00000)
    assert dtcm_base(raw, 0x02000000) == 0x02E00000
    struct.pack_into('<I', raw, 8, 0xEE093F11)
    with pytest.raises(ValueError, match='uniquely declared'):
        dtcm_base(raw, 0x02000000)
