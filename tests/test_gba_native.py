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
from decompnet.gba_native import export, inspect, _profile, _regions, _sdk, _feedback, SDK_COMMIT
from .fixtures.gba_native import hardware, timer_micro, bios_pipeline, bios_sound, callbacks, PROGRAM


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


def generate(work, *, profile=True, mutate=None, feedback=(), fixture=None,bios=None,relocated=True):
    work.mkdir()
    data, document = hardware() if fixture is None else fixture
    if mutate:
        data = mutate(data)
        document['input_sha256'] = hashlib.sha256(data).hexdigest()
    rom = work/'original.gba'; rom.write_bytes(data)
    mapping = work/'profile.json'; mapping.write_text(json.dumps(document))
    output = work/'Independent GBA source with spaces'
    result = export(rom, output, profile=mapping if profile else None, save_type='sram', feedback=feedback,bios=bios)
    assert result['integrity_verified'] and not result['host_build_verified']
    assert result['manifest']['runtime']['revision'] == SDK_COMMIT
    assert result['manifest']['fallback'] == dict(interpreter=True, runtime_compilation=False)
    assert result['manifest']['output_kind'] == 'cpu-probe'
    assert not result['presentation_declared'] and not result['gameplay_verified']
    if not relocated:
        # Fault-inject an incomplete older compiled registry to exercise strict
        # failure and feedback import even when current inference covers it.
        (output/'game/relocated_dispatch.c').write_text('#include <anygba/relocated.h>\n'
            'const anygba_relocated_entry* const anygba_relocated_entries=0;\n'
            'const uint32_t anygba_relocated_count=0;\n')
    run([sys.executable, '-I', output/'tools/extract_assets.py', rom])
    run(['cmake', '-S', output, '-B', output/'build', '-DCMAKE_BUILD_TYPE=Release'])
    run(['cmake', '--build', output/'build', '--config', 'Release', '--parallel', '2'])
    exe = next(p for p in (output/'build/gba_probe', output/'build/gba_probe.exe',
        output/'build/Release/gba_probe.exe') if p.is_file())
    return rom, output, exe


@pytest.fixture(scope='module')
def original(tmp_path_factory, sdk):
    return generate(tmp_path_factory.mktemp('gba-source')/'fixture')


def execute(original, *options, ok=True, frames=8):
    rom, root, exe = original
    output = run([exe, '--rom', root/'assets/game.gba', '--frames', str(frames), *options], ok=ok)
    return json.loads(output) if ok else output


def test_callback_tables_reached_through_ram_compile_without_profiles_or_feedback(tmp_path,sdk):
    project=generate(tmp_path/'callbacks',profile=False,fixture=callbacks())
    options=[v for address in [*range(0x02000004,0x02000044,4),0x02000048,0x0200004c,0x02000050]
             for v in ('--observe',hex(address))]
    native=execute(project,'--strict-static',*options)
    reference=execute(project,'--interpreter',*options)
    assert native['observed']==[11,22,33,44,55,33,25,7,42,55,12,13,69,79,89,42,77,97,2300]
    assert native['misses']==[] and native['interpreted_cycles']==0
    for field in ('observed','frames','cycles','screen_sha256','audio_frames'):
        assert native[field]==reference[field],field
    assert 'ROM callback-table entry hypotheses' in (project[1]/'analysis.json').read_text()
    assert json.loads((project[1]/'analysis.json').read_text())['automatic_ram_code']
    # Storing the instruction PC makes a copied body placement-dependent.
    # Its ROM-compiled constant must never be reused at a stack address.
    assert 'static coverage miss' in execute(project,'--keys','2','--strict-static',ok=False)
    moved=execute(project,'--keys','2','--observe','0x02000044')
    oracle=execute(project,'--keys','2','--interpreter','--observe','0x02000044')
    assert moved['observed']==oracle['observed']==[0x03007eec]
    assert moved['misses'] and moved['interpreted_cycles']>0


def test_original_native_code_drives_bios_keys_irq_dma_picture_audio_and_save(original, tmp_path):
    _, root, _ = original
    save = tmp_path/'cartridge.sav'; image = tmp_path/'image.ppm'; pcm = tmp_path/'sound.pcm'
    args = [v for address in range(0x02000000, 0x02000028, 4) for v in ('--observe', hex(address))]
    report = execute(original, '--strict-static', '--keys', '1', '--save', save, '--capture', image,
                     '--audio-pcm', pcm, *args)
    assert report['observed'][:9] == [255, 0, 14, 2, 42, 1022, 7, 77, 90]
    assert report['observed'][9] > 0
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
    observations = [v for address in range(0x02000000, 0x02000028, 4) for v in ('--observe', hex(address))]
    compiled = execute(original, '--strict-static', '--keys', '0x301', '--save', tmp_path/'native.sav', *observations)
    reference = execute(original, '--interpreter', '--keys', '0x301', '--save', tmp_path/'reference.sav', *observations)
    assert reference['interpreted_cycles'] > 0 and compiled['interpreted_cycles'] == 0
    for field in ('observed', 'frames', 'screen_sha256', 'audio_frames'):
        assert reference[field] == compiled[field], field
    assert (tmp_path/'native.sav').read_bytes() == (tmp_path/'reference.sav').read_bytes()


@pytest.mark.parametrize('instructions,expected', [(0,7),(1,13),(16,103)])
def test_live_timer_load_phase_matches_independent_mgba(instructions, expected, tmp_path, sdk):
    project=generate(tmp_path/'timer',fixture=timer_micro(instructions))
    for mode in ('--strict-static','--interpreter'):
        result=execute(project,mode,'--observe','0x02000000','--observe','0x02000004')
        assert result['observed']==[expected,expected]


def test_ram_code_modified_after_export_is_never_executed_as_stale_native_code(original, tmp_path):
    feedback = tmp_path/'modified-ram.txt'
    report = execute(original, '--keys', '2', '--observe', '0x0200001c', '--miss-log', feedback)
    assert report['observed'] == [76] and report['interpreted_cycles'] > 0
    assert 0x03000000 in report['misses']
    assert '0x03000000 arm' in feedback.read_text()
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
    project = generate(tmp_path/'unprofiled', profile=False,relocated=False)
    feedback = tmp_path/'coverage.txt'
    result = execute(project, '--miss-log', feedback)
    assert result['interpreted_cycles'] > 0 and result['misses']
    assert '0x03000040 thumb rom=' in feedback.read_text() and 'size=0x00000004' in feedback.read_text()
    assert 'static coverage miss' in execute(project, '--strict-static', ok=False)
    recovered = generate(tmp_path/'feedback', profile=False, feedback=[feedback])
    report = execute(recovered, '--strict-static')
    assert report['interpreted_cycles'] == 0 and report['misses'] == []
    assert report['screen_sha256'] == result['screen_sha256']
    assert json.loads((recovered[1]/'analysis.json').read_text())['feedback'][0]['records'] > 0


def test_feedback_preserves_existing_files_and_checks_input_identity(original, tmp_path):
    path = tmp_path/'coverage.txt'
    path.write_text('existing diagnostics')
    assert 'existing work is preserved' in execute(original, '--miss-log', path, ok=False)
    assert path.read_text() == 'existing diagnostics'
    data, _ = hardware()
    path.write_text('# decomp.wtf.gba-misses/v1 sha256='+'0'*64+'\n')
    with pytest.raises(pc.PCError, match='SHA-256 differs'):
        _feedback(path, hashlib.sha256(data).hexdigest(), len(data))
    path.write_text('# decomp.wtf.gba-misses/v1 sha256='+hashlib.sha256(data).hexdigest()+'\n0x02080000 arm\n')
    with pytest.raises(pc.PCError, match='outside the input'):
        _feedback(path, hashlib.sha256(data).hexdigest(), len(data))


def test_feedback_recovers_temporal_and_overlapping_ram_copies(tmp_path, sdk, monkeypatch):
    # Isolate the feedback importer from automatic copy inference. These copies
    # are now discovered during an ordinary export; an older/incomplete export
    # must still record both byte variants at a shared execution address.
    import decompnet.gba_native as gba
    with monkeypatch.context() as patch:
        patch.setattr(gba, '_automatic_copies', lambda *_args: ([], [], []))
        original = generate(tmp_path/'before-copy-inference',relocated=False)
    feedback = tmp_path/'overlays.txt'
    observations = [v for a in range(0x02000028, 0x02000038, 4) for v in ('--observe', hex(a))]
    native = execute(original, '--keys', '0x40', '--miss-log', feedback, *observations)
    assert native['observed'] == [91, 92, 8, 9]
    # Both versions at one address must survive the miss recorder's deduplication.
    records = [line for line in feedback.read_text().splitlines() if line.startswith('0x03000080 arm rom=')]
    assert len(records) == 2 and records[0] != records[1]
    recovered = generate(tmp_path/'overlays', feedback=[feedback])
    result = execute(recovered, '--keys', '0x40', '--strict-static', *observations)
    reference = execute(recovered, '--keys', '0x40', '--interpreter', *observations)
    assert result['observed'] == reference['observed'] == native['observed']
    assert result['interpreted_cycles'] == 0 and not result['misses']
    # An independent mutation must still use fallback, even with alternate versions.
    assert execute(recovered, '--keys', '2', '--observe', '0x0200001c')['observed'] == [76]
    # Reviewed profiles can also describe simultaneous/temporal overlapping views.
    from decompnet.gba_native import _overlay_regions
    data,profile=hardware()
    profile['ram_code']=_overlay_regions(profile,[(feedback.read_text(),{})],len(data))
    reviewed=generate(tmp_path/'reviewed-overlays',fixture=(data,profile))
    assert execute(reviewed,'--keys','0x40','--strict-static',*observations)['observed']==native['observed']


def test_unsupported_bios_service_stops_instead_of_returning_success(tmp_path, sdk):
    def patched(data):
        data = bytearray(data)
        index = data.index(struct.pack('<I', 0xef060000))
        struct.pack_into('<I', data, index, 0xef1a0000)
        struct.pack_into('<H', data, PROGRAM['symbols']['thumb_code']-0x08000000, 0xdf1a)
        return bytes(data)
    project = generate(tmp_path/'bios-guard', mutate=patched)
    assert 'unsupported GBA BIOS service 26' in execute(project, ok=False)
    # Original 16 KiB test firmware: supervisor stack save/restore, r0=123,
    # exception return using SPSR. No console BIOS bytes or external firmware.
    bios = tmp_path/'original-bios.bin'; image = bytearray(16384)
    struct.pack_into('<4I', image, 8, 0xe92d4010, 0xe3a0007b, 0xe8bd4010, 0xe1b0f00e)
    bios.write_bytes(image)
    report = execute(project, '--bios', bios, '--observe', '0x02000008', '--observe', '0x02000010')
    assert report['observed'] == [123,246] and report['interpreted_cycles'] > 0
    reference=execute(project,'--bios',bios,'--interpreter','--observe','0x02000008','--observe','0x02000010')
    assert reference['observed']==report['observed']
    assert report['bios_sha256'] == hashlib.sha256(image).hexdigest()
    assert not report['misses']  # Firmware addresses must not pollute cartridge feedback.
    assert 'strict static mode rejects' in execute(project, '--bios', bios, '--strict-static', ok=False)
    bios.write_bytes(bytes(4096)); save=tmp_path/'untouched.sav'
    assert '16384 bytes' in execute(project, '--bios', bios, '--save', save, ok=False)
    assert not save.exists()


def test_owner_bios_pipeline_protection_and_irq_vector_match_independent_mgba(tmp_path, sdk):
    fixture,image=bios_pipeline()
    project=generate(tmp_path/'bios-pipeline',fixture=fixture)
    bios=tmp_path/'original-bios.bin';bios.write_bytes(image)
    addresses=[*range(0x02000000,0x02000024,4),0x02000040,0x02000044]
    observations=[v for address in addresses for v in ('--observe',hex(address))]
    expected=[0x89abcdef,0x12345678,0x1234,0x56,0x12345678,0x5aa5,0,0x5a,0x31415926,99,77]
    for options in ((),('--interpreter',)):
        result=execute(project,'--bios',bios,*options,*observations)
        assert result['observed']==expected
        assert result['interpreted_cycles']>0
        assert all(address>=0x02000000 for address in result['misses'])
        if not options:
            assert not result['misses']


def test_translated_bios_executes_vectors_thumb_and_irqs_with_zero_interpreter_cycles(tmp_path,sdk):
    fixture,image=bios_pipeline();bios=tmp_path/'original-firmware.bin';bios.write_bytes(image)
    project=generate(tmp_path/'native-bios',fixture=fixture,bios=bios)
    observations=[v for address in [*range(0x02000000,0x02000024,4),0x02000040,0x02000044]
                  for v in ('--observe',hex(address))]
    native=execute(project,'--strict-static',*observations)
    reference=execute(project,'--interpreter',*observations)
    assert native['observed']==[0x89abcdef,0x12345678,0x1234,0x56,0x12345678,0x5aa5,0,0x5a,0x31415926,99,77]
    assert native['interpreted_cycles']==0 and native['misses']==[]
    assert native['bios_native_dispatches']>0 and reference['bios_native_dispatches']==0
    for field in ('observed','frames','cycles','screen_sha256','audio_frames','bios_sha256'):
        assert native[field]==reference[field],field
    manifest=json.loads((project[1]/'pc-project.json').read_text())
    assert manifest['firmware']['mode']=='compiled' and manifest['inputs'][1]['kind']=='bios'
    changed=bytearray(image);changed[-1]^=1;bios.write_bytes(changed)
    assert 'strict static mode rejects' in execute(project,'--bios',bios,'--strict-static',ok=False)


@pytest.mark.parametrize('mode,active_bytes,checksum',[
    ('fixed-loop',3168,434383957),
    ('resampled-loop',3162,2270628090),
    ('one-shot',0,2543690053),
])
def test_optional_owner_bios_sound_driver_mixes_and_clears_original_pcm(mode, active_bytes, checksum, tmp_path, sdk):
    image=os.environ.get('DECOMP_GBA_TEST_BIOS')
    if not image:
        pytest.skip('owner-run BIOS sound qualification; set DECOMP_GBA_TEST_BIOS to a 16 KiB image')
    bios=Path(image).resolve()
    assert bios.is_file() and bios.stat().st_size==16384
    project=generate(tmp_path/'sound',fixture=bios_sound(mode),bios=bios)
    addresses=[*range(0x02000000,0x02000054,4),*range(0x02003000,0x02003090,4)]
    observations=[v for address in addresses for v in ('--observe',hex(address))]
    reports=[];pcm=[]
    for name,options in (('native',('--strict-static',)),('reference',('--interpreter',))):
        capture=tmp_path/(name+'.pcm')
        result=execute(project,'--bios',bios,*options,'--audio-pcm',capture,*observations,frames=96)
        if name=='native':
            assert result['interpreted_cycles']==0 and result['bios_native_dispatches']>0
            assert not result['misses']
        else:
            assert result['interpreted_cycles']>0 and result['bios_native_dispatches']==0
        values=result['observed'][:21]
        assert all(0<address<16384 and address&1 for address in result['observed'][21:])
        assert values[0]==0x68736d53  # BIOS SoundInfo identity
        assert values[1]&0xffffff00==0x0f010000  # no reverb, one channel, master volume 15
        assert values[3:6]==[176,10512,8192]  # samples/VBlank, mixer Hz, MIDI frequency
        assert bool(values[6]&0xff)==(mode!='one-shot') and values[8]&0xff==0
        assert values[9]==0 and values[10]&~0x60==0xb600 and values[11]==1
        assert values[16]>=80 and values[17]==80  # IRQ and music callbacks
        assert values[18:21]==[active_bytes,checksum,0]  # independent mGBA buffer FNV-1a, then silence
        samples=struct.unpack('<'+'h'*(capture.stat().st_size//2),capture.read_bytes())
        assert max(samples)>1000 and min(samples)<-1000
        assert any(left!=right for left,right in zip(samples[::2],samples[1::2]))
        assert not any(samples[-4096:])
        reports.append(result);pcm.append(capture.read_bytes())
    assert reports[0]['observed']==reports[1]['observed']
    assert pcm[0]==pcm[1]


def test_multiboot_without_a_cable_returns_failure_instead_of_stopping(tmp_path, sdk):
    def patched(data):
        data=bytearray(data);index=data.index(struct.pack('<I',0xef060000))
        struct.pack_into('<I',data,index,0xef250000)
        return bytes(data)
    project=generate(tmp_path/'no-cable',mutate=patched)
    report=execute(project,'--strict-static','--observe','0x02000008')
    assert report['observed']==[1] and report['interpreted_cycles']==0


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


def test_gba_game_backend_is_experimental_and_inspection_validates_header(tmp_path):
    assert pc.status('gba')['available'] and pc.status('gba')['experimental']
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


def test_combined_feedback_preserves_distinct_ram_copies_independent_of_log_order():
    from decompnet.gba_native import _feedback_regions
    # Two copied functions, then an interior entry in the first copy. The old
    # end-of-RAM inference let the second record hide the first function.
    a = ('# identity\n0x03002000 arm rom=0x08000100\n', {})
    b = ('# identity\n0x03001000 thumb rom=0x08001000\n', {})
    c = ('# identity\n0x03002100 arm rom=0x08000200\n', {})
    expected = [dict(address=0x03001000,rom=0x08001000,size=0x1000,mode='thumb'),
                dict(address=0x03002000,rom=0x08000100,size=0x6000,mode='arm')]
    assert _feedback_regions({}, [a,b,c], 0x10000) == expected
    assert _feedback_regions({}, [c,b,a], 0x10000) == expected
    conflict = ('# identity\n0x03002000 arm rom=0x08000500\n', {})
    rows = _feedback_regions({}, [a,b,c,conflict], 0x10000)
    assert all(r['address'] != 0x03002000 for r in rows)
    assert rows[0]['address']+rows[0]['size'] == 0x03002000
    reviewed = dict(ram_code=[dict(address=0x03002000,rom=0x08000100,size=0x200,mode='arm')])
    assert _feedback_regions(reviewed, [a,b,c], 0x10000) == expected[:1]
    short = ('# identity\n0x03000040 thumb rom=0x08000200 size=0x00000004\n', {})
    assert _feedback_regions({}, [short], 0x10000) == [dict(address=0x03000040,rom=0x08000200,size=4,mode='thumb')]
    mixed = ('# identity\n0x03000000 thumb rom=0x08001000\n0x03000010 arm rom=0x08001010\n', {})
    # Instruction-set switches inside one copied image must not split the span
    # used by whole-function byte guards. Both entry modes remain in the log.
    assert _feedback_regions({}, [mixed], 0x10000) == [dict(address=0x03000000,rom=0x08001000,size=0x8000,mode='thumb')]


def test_short_ram_feedback_requires_an_aligned_backed_signature(tmp_path):
    data, _ = hardware(); digest = hashlib.sha256(data).hexdigest()
    path = tmp_path/'bounded.txt'
    header = '# decomp.wtf.gba-misses/v1 sha256='+digest+'\n'
    row = '0x03000040 thumb rom=0x080000c0 size='
    path.write_text(header+row+'0x00000004\n')
    content, pin = _feedback(path, digest, len(data))
    assert pin['records'] == 1 and 'size=0x00000004' in content
    for size in ('0x0', '0x3', '0x40'):
        path.write_text(header+row+size+'\n')
        with pytest.raises(pc.PCError, match='signature size'):
            _feedback(path, digest, len(data))
