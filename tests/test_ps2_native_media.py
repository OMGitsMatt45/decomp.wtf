"""Original PS2 disc/ELF input fixtures; never use retail bytes in CI."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import struct

import pycdlib
import pytest

from decompnet.pc import PCError
from decompnet.ps2_native import media
from decompnet.ps2_native.reports import generation_report
from decompnet.rom.psx import _Disc
from tests.fixtures.ps2_native import BASE, program
from decompnet.ps2_native.modules import mwo3_elf


def disc(path, *, nested=False, boot=b'cdrom0:\\SLUS_999.99;1', extra=None):
    image = pycdlib.PyCdlib(); image.new(interchange_level=3, vol_ident='PS2_ORIGINAL')
    if nested:
        image.add_directory('/BIN'); boot = b'cdrom0:\\BIN\\SLUS_999.99;1'
    raw, _, _ = program()
    irx = bytearray(raw); struct.pack_into('<H', irx, 16, 0xFF80)
    image.add_directory('/MODULES')
    entries = {'/SYSTEM.CNF;1': b'BOOT2 = ' + boot + b'\r\nVER = 1.00\r\n',
        ('/BIN' if nested else '') + '/SLUS_999.99;1': raw,
        '/MODULES/ORIGINAL.IRX;1': irx}
    entries.update(extra or {})
    for name, data in entries.items(): image.add_fp(BytesIO(data), len(data), iso_path=name)
    image.write(str(path)); image.close()
    return raw


def test_streaming_nested_disc_reports_boot_and_iop_without_enabling_a_game(tmp_path):
    path = tmp_path / 'original.iso'; raw = disc(path, nested=True)
    result = media.inspect(path)
    assert result['program']['boot'] == 'BIN/SLUS_999.99'
    assert result['program']['game_code'] == 'SLUS-99999'
    assert result['program']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['iop_modules'] == ['MODULES/ORIGINAL.IRX']
    assert result['input']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['input']['identity_verified']
    assert not result['native_game_qualified'] and not result['app_backend_registered']


def test_stripped_program_preserves_overlapping_bss_loads(tmp_path):
    raw, code, _ = program(); raw = bytearray(raw)
    struct.pack_into('<I', raw, 32, 0)  # no section table or symbols
    struct.pack_into('<HHH', raw, 46, 0, 0, 0)
    struct.pack_into('<H', raw, 44, 3)
    struct.pack_into('<I', raw, 52 + 20, len(code) + 0x100)
    for index, size in ((1, 0x20), (2, 0x40)):
        struct.pack_into('<8I', raw, 52 + 32 * index, 1, 0x100 + len(code), BASE + len(code), BASE + len(code), 0, size, 7, 16)
    path = tmp_path / 'SLUS_999.99'; path.write_bytes(raw)
    info = media.inspect(path)['program']
    assert info['stripped'] and len(info['loads']) == 3
    assert len(info['overlapping_loads']) == 3
    assert all(not overlap['includes_file_bytes'] for overlap in info['overlapping_loads'])
    assert [s['file_size'] for s in info['loads'][1:]] == [0, 0]


@pytest.mark.parametrize('offset,fmt,value', [
    (44, '<H', 300), (42, '<H', 31), (24, '<I', 0x03000000),
    (52 + 4, '<I', 0xFFFFFF00), (52 + 20, '<I', 0x03000000),
    (32, '<I', 0xFFFFFF00), (16, '<H', 0xFF80),
])
def test_rejects_malformed_or_non_ee_programs(offset, fmt, value):
    raw = bytearray(program()[0]); struct.pack_into(fmt, raw, offset, value)
    with pytest.raises(PCError): media.elf_info(raw)


def test_dvd_extents_above_four_gib_are_read_without_loading_the_image(tmp_path, monkeypatch):
    path = tmp_path / 'large sparse DVD.iso'; raw = disc(path)
    with path.open('r+b') as stream:
        if os.name == 'nt':
            import ctypes
            import msvcrt
            returned = ctypes.c_uint32()
            assert ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno())),
                ctypes.c_uint32(0x900C4), None, 0, None, 0, ctypes.byref(returned), None)
        image = _Disc(stream); pvd = image.sector(16)
        records = list(image.records(int.from_bytes(pvd[158:162], 'little'), int.from_bytes(pvd[166:170], 'little'), offsets=True))
        item = next(r for r in records if r['path'] == 'SLUS_999.99')
        address = (1 << 32) + 0x4000; lba = address // 2048
        blocks = lba + (len(raw) + 2047) // 2048
        stream.seek(item['record_offset'] + 2); stream.write(struct.pack('<I', lba) + struct.pack('>I', lba))
        stream.seek(16 * 2048 + 80); stream.write(struct.pack('<I', blocks) + struct.pack('>I', blocks))
        stream.truncate(blocks * 2048); stream.seek(address); stream.write(raw)
    actual_open = Path.open; reads = []
    class BoundedReader:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def seek(self, *args): return self.stream.seek(*args)
        def tell(self): return self.stream.tell()
        def fileno(self): return self.stream.fileno()
        def read(self, size=-1):
            assert 0 <= size <= 1024 * 1024
            reads.append(size); return self.stream.read(size)
    monkeypatch.setattr(Path, 'open', lambda self, *a, **k: BoundedReader(actual_open(self, *a, **k)))
    result = media.inspect(path, hash_input=False)
    assert result['program']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['input']['size'] > 1 << 32 and result['input']['sha256'] is None
    assert not result['input']['identity_verified']
    assert sum(reads) < 64 * 1024


@pytest.mark.parametrize('boot', [b'cdrom0:\\..\\SLUS_999.99;1', b'cdrom0:\\MISSING.ELF;1', b'host:SLUS_999.99'])
def test_boot_paths_cannot_escape_the_disc_or_name_missing_files(tmp_path, boot):
    path = tmp_path / 'original.iso'; disc(path, boot=boot)
    with pytest.raises(PCError): media.inspect(path)


def test_inspection_rejects_input_changes(tmp_path, monkeypatch):
    path = tmp_path / 'original.iso'; disc(path)
    actual_hash = media._hash
    def change(stream):
        result = actual_hash(stream)
        with path.open('ab') as writer: writer.write(b'changed')
        return result
    monkeypatch.setattr(media, '_hash', change)
    with pytest.raises(PCError, match='changed during inspection'): media.inspect(path)


def test_zero_exit_and_zero_decode_failures_do_not_hide_emission_errors():
    summary = 'Functions processed: 19, recompiled: 19, stubs: 0, skipped: 0, decode failures: 0\n'
    with pytest.raises(PCError, match='errors=3'):
        generation_report(summary + 'Warnings: 2, errors: 3\nRecompilation completed successfully')
    with pytest.raises(PCError, match='incomplete'): generation_report(summary)
    report = generation_report(summary + 'Warnings: 2, errors: 0', expected_functions=19)
    assert report['errors'] == 0 and report['warnings'] == 2


def overlay(module_id=7, load=0x500000):
    code = b'\x08\x00\xe0\x03\0\0\0\0'  # original JR $ra / NOP
    data = struct.pack('<II', load + 64, 0)
    header = struct.pack('<4s7I32s', b'MWo3', module_id, load, len(code), len(data), 32,
        load + 64 + len(code), load + 64 + len(code) + len(data), b'original.bin')
    return header + code + data


def test_generic_metrowerks_overlays_share_addresses_with_independent_identities(tmp_path):
    one, two = overlay(7), overlay(13)
    path = tmp_path / 'original.iso'
    disc(path, extra={'/MODULES/ONE.BIN;1': one, '/MODULES/TWO.BIN;1': two})
    modules = media.inspect(path)['overlays']
    assert [m['id'] for m in modules] == [7, 13]
    assert modules[0]['load_address'] == modules[1]['load_address'] == 0x500000
    assert modules[0]['sha256'] != modules[1]['sha256']
    assert modules[0]['constructors'] == [0x500040, 0]
    assert modules[0]['bss_size'] == 32 and not modules[0]['elf_reservations']
    analyzed = media.inspect(path, discover_code=True)['overlays']
    assert all(m['code_discovery']['instructions'] == 2 for m in analyzed)
    assert all(m['code_discovery']['entry_role'] == 'synthetic-overlay-text-start' for m in analyzed)
    assert analyzed[0]['code_discovery']['original_elf_sha256'] != analyzed[1]['code_discovery']['original_elf_sha256']


@pytest.mark.parametrize('offset,value', [(8, 0x1FFFFFF), (12, 0x10000), (24, 0x400000), (28, 0x600000)])
def test_mwo3_rejects_invalid_ranges_and_constructor_tables(offset, value):
    raw = bytearray(overlay()); struct.pack_into('<I', raw, offset, value)
    with pytest.raises(PCError): media.mwo3_info(raw)


@pytest.mark.parametrize('load', [0x500000, 0x80040000, 0xA0120000])
def test_mwo3_analysis_elf_preserves_load_image_and_separates_data(load):
    from elftools.elf.elffile import ELFFile
    original = overlay(19, load)
    wrapped = mwo3_elf(original)
    facts = media.elf_info(wrapped)
    elf = ELFFile(BytesIO(wrapped))
    segment = elf.get_segment(0)
    assert segment.data() == original
    assert segment['p_vaddr'] == load
    assert segment['p_memsz'] == len(original) + 32
    assert elf.get_section_by_name('.mwo3').data() == original[:64]
    assert elf.get_section_by_name('.text').data() == original[64:72]
    assert elf.get_section_by_name('.data').data() == original[72:]
    assert elf.get_section_by_name('.bss')['sh_type'] == 'SHT_NOBITS'
    assert not elf.get_section_by_name('.data')['sh_flags'] & 4
    assert facts['executable_sections'] == [dict(index=2, address=load + 64, size=8, offset=0x140)]
    assert facts['stripped'] and facts['entry'] == load + 64


def test_mwo3_analysis_does_not_guess_an_unknown_module_layout():
    with pytest.raises(PCError, match='MWo3'):
        mwo3_elf(b'unknown overlay format')
