"""Build and execute original GBA ARM/Thumb against the source-shipped core."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

from decompnet import pc, toolchains
from decompnet.gba_native import export, inspect, _profile, _regions, _sdk, SDK_COMMIT
from .fixtures.gba_native import hardware


@pytest.fixture(scope='module')
def sdk():
    if toolchains.installed('anygba-sdk') is None or shutil.which('cmake') is None:
        if os.environ.get('DECOMP_REQUIRE_GBA_NATIVE') == '1':
            pytest.fail('GBA qualification requires pinned anygba-sdk and CMake')
        pytest.skip('optional GBA native translator sources and CMake are not installed')


def run(command, *, ok=True, **kwargs):
    result = subprocess.run(list(map(str,command)), capture_output=True, text=True, timeout=180, **kwargs)
    if ok:
        assert result.returncode == 0, result.stdout+result.stderr
        return result.stdout
    assert result.returncode != 0
    return result.stderr


def generate(work, *, profile=True, mutate=None):
    work.mkdir()
    data, document = hardware()
    if mutate:
        data = mutate(data)
        document['input_sha256'] = hashlib.sha256(data).hexdigest()
    rom = work/'original.gba'; rom.write_bytes(data)
    mapping = work/'profile.json'; mapping.write_text(json.dumps(document))
    output = work/'Independent GBA source with spaces'
    result = export(rom, output, profile=mapping if profile else None, save_type='sram')
    assert result['integrity_verified'] and not result['host_build_verified']
    assert result['manifest']['runtime']['revision'] == SDK_COMMIT
    assert result['manifest']['fallback'] == dict(interpreter=True, runtime_compilation=False)
    assert result['manifest']['output_kind'] == 'cpu-probe'
    assert not result['presentation_declared'] and not result['gameplay_verified']
    run([sys.executable, '-I', output/'tools/extract_assets.py', rom])
    run(['cmake', '-S', output, '-B', output/'build', '-DCMAKE_BUILD_TYPE=Release'])
    run(['cmake', '--build', output/'build', '--config', 'Release', '--parallel', '2'])
    exe = next(p for p in (output/'build/gba_probe', output/'build/gba_probe.exe',
        output/'build/Release/gba_probe.exe') if p.is_file())
    return rom, output, exe


@pytest.fixture(scope='module')
def original(tmp_path_factory, sdk):
    return generate(tmp_path_factory.mktemp('gba-source')/'fixture')


def execute(original, *options, ok=True):
    rom, root, exe = original
    output = run([exe, '--rom', root/'assets/game.gba', '--frames', '8', *options], ok=ok)
    return json.loads(output) if ok else output


def test_original_native_code_drives_bios_keys_irq_dma_picture_audio_and_save(original, tmp_path):
    _, root, _ = original
    save = tmp_path/'cartridge.sav'; image = tmp_path/'image.ppm'; pcm = tmp_path/'sound.pcm'
    args = [v for address in range(0x02000000, 0x02000020, 4) for v in ('--observe', hex(address))]
    report = execute(original, '--strict-static', '--keys', '1', '--save', save, '--capture', image,
                     '--audio-pcm', pcm, *args)
    assert report['observed'] == [255, 0, 14, 2, 42, 1022, 7, 77]
    assert report['interpreted_cycles'] == 0 and report['misses'] == []
    assert not report['gpu_rendering'] and not report['retail_qualified']
    assert image.read_bytes() == b'P6\n240 160\n255\n'+b'\xff\x00\x00'*(240*160)
    samples = struct.unpack('<'+'h'*(pcm.stat().st_size//2), pcm.read_bytes())
    assert max(samples) > 1000 and min(samples) < -1000
    assert len(samples) == report['audio_frames']*2
    assert save.stat().st_size == 32768 and save.read_bytes()[0] == 0
    again = execute(original, '--strict-static', '--save', save, *args)
    assert again['observed'][:2] == [0, 1] and save.read_bytes()[0] == 1
    assert (root/'runtime/anygba/LICENSE').read_text().startswith('MIT License')
    assert pc.verify(root)['integrity_verified']


def test_translated_and_reference_cpu_agree_on_original_hardware(original, tmp_path):
    observations = [v for address in range(0x02000000, 0x02000020, 4) for v in ('--observe', hex(address))]
    compiled = execute(original, '--strict-static', '--keys', '0x301', '--save', tmp_path/'native.sav', *observations)
    reference = execute(original, '--interpreter', '--keys', '0x301', '--save', tmp_path/'reference.sav', *observations)
    assert reference['interpreted_cycles'] > 0 and compiled['interpreted_cycles'] == 0
    for field in ('observed', 'frames', 'screen_sha256', 'audio_frames'):
        assert reference[field] == compiled[field], field
    assert (tmp_path/'native.sav').read_bytes() == (tmp_path/'reference.sav').read_bytes()


def test_ram_code_modified_after_export_is_never_executed_as_stale_native_code(original):
    report = execute(original, '--keys', '2', '--observe', '0x0200001c')
    assert report['observed'] == [76] and report['interpreted_cycles'] > 0
    assert 'static coverage miss' in execute(original, '--keys', '2', '--strict-static', ok=False)


def test_unknown_assets_fail_before_save_or_capture_side_effects(original, tmp_path):
    rom, root, exe = original
    bad = tmp_path/'wrong.gba'; data = bytearray(rom.read_bytes()); data[-1] ^= 1; bad.write_bytes(data)
    save = tmp_path/'must-not-exist.sav'; capture = tmp_path/'must-not-exist.ppm'
    error = run([exe, '--rom', bad, '--save', save, '--capture', capture], ok=False)
    assert 'SHA-256 differs' in error and not save.exists() and not capture.exists()
    before = (root/'assets/game.gba').read_bytes()
    assert 'SHA-256 differs' in run([sys.executable, '-I', root/'tools/extract_assets.py', bad], ok=False)
    assert (root/'assets/game.gba').read_bytes() == before


@pytest.mark.parametrize('args', [('--frames', '0'), ('--frames', '-1'), ('--keys', '1024'),
    ('--observe', '0x04000000'), ('--observe', '0x02000001'), ('--strict-static', '--interpreter'), ('--bogus', '1')])
def test_probe_rejects_invalid_run_options(original, args):
    assert execute(original, *args, ok=False)


def test_missing_code_map_reports_fallback_and_strict_mode_stops(tmp_path, sdk):
    project = generate(tmp_path/'unprofiled', profile=False)
    result = execute(project)
    assert result['interpreted_cycles'] > 0 and result['misses']
    assert 'static coverage miss' in execute(project, '--strict-static', ok=False)


def test_unsupported_bios_service_stops_instead_of_returning_success(tmp_path, sdk):
    def patched(data):
        data = bytearray(data)
        index = data.index(struct.pack('<I', 0xef060000))
        struct.pack_into('<I', data, index, 0xef1a0000)
        return bytes(data)
    project = generate(tmp_path/'bios-guard', mutate=patched)
    assert 'unsupported GBA BIOS service 26' in execute(project, ok=False)


def test_wrong_profile_identity_and_output_reuse_preserve_existing_work(original, tmp_path):
    rom, root, _ = original
    data, document = hardware(); document['input_sha256'] = '0'*64
    profile = tmp_path/'wrong.json'; profile.write_text(json.dumps(document))
    output = tmp_path/'must-not-exist'
    with pytest.raises(pc.PCError, match='SHA-256 differs'):
        export(rom, output, profile=profile)
    assert not output.exists()
    with pytest.raises(pc.PCError, match='existing work'):
        export(rom, root)
    assert pc.verify(root)['integrity_verified']


def test_gba_probe_does_not_advertise_a_finished_gpu_game_backend(tmp_path):
    assert not pc.status('gba')['available']
    data, _ = hardware(); rom = tmp_path/'fixture.gba'; rom.write_bytes(data)
    assert inspect(rom)['game_code'] == 'TSTE'
    bad = bytearray(data); bad[0xbd] ^= 1; rom.write_bytes(bad)
    with pytest.raises(pc.PCError, match='checksum'):
        inspect(rom)


def test_gba_profiles_reject_foreign_code_and_misaligned_entries(tmp_path):
    data, doc = hardware()
    doc['entries'][0]['address'] |= 1
    mapping = tmp_path/'mapping.json'; mapping.write_text(json.dumps(doc))
    with pytest.raises(pc.PCError, match='misaligned'):
        _profile(mapping, hashlib.sha256(data).hexdigest())
    doc['entries'] = []; doc['replace'] = [{'function': 'return_zero'}]
    mapping.write_text(json.dumps(doc))
    with pytest.raises(pc.PCError, match='only code entries'):
        _profile(mapping, hashlib.sha256(data).hexdigest())


def test_gba_regions_reject_code_without_backing_bytes():
    data, profile = hardware()
    profile['ram_code'][0]['size'] = 0x8000
    with pytest.raises(pc.PCError, match='aligned original ROM'):
        _regions(profile, len(data))
    profile['ram_code'] = []
    profile['entries'] = [dict(address=0x03000000, mode='arm')]
    with pytest.raises(pc.PCError, match='outside the cartridge'):
        _regions(profile, len(data))


def test_edited_source_cache_is_rejected_before_building(tmp_path, monkeypatch):
    for name in ('common', 'tools/recomp', 'runtime'):
        (tmp_path/name).mkdir(parents=True)
    (tmp_path/'LICENSE').write_text('MIT with missing or edited sources')
    monkeypatch.setattr(toolchains, 'ensure', lambda *_a, **_k: tmp_path)
    with pytest.raises(pc.PCError, match='pinned SDK'):
        _sdk()
