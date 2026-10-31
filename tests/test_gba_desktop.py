"""Build a standalone desktop export and exercise its actual presentation paths."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from decompnet import pc
from decompnet.gba_native import export_game
from .fixtures.gba_native import hardware
from .test_gba_native import run, sdk


def binary(root, name):
    return next(p for p in (root/'build'/name, root/'build'/(name+'.exe'),
                            root/'build/Release'/(name+'.exe')) if p.is_file())


@pytest.fixture(scope='module')
def desktop(tmp_path_factory, sdk):
    work = tmp_path_factory.mktemp('gba-desktop')
    data, profile = hardware()
    rom = work/'original.gba'; rom.write_bytes(data)
    mapping = work/'profile.json'; mapping.write_text(json.dumps(profile))
    root = work/'Independent desktop with spaces'
    result = export_game(rom, root, profile=mapping, save_type='sram')
    assert result['presentation_declared'] and not result['gameplay_verified']
    assert result['manifest']['output_kind'] == 'game'
    assert result['manifest']['build']['target'] == 'gba_pc'
    assert result['manifest']['execution_model']=='static-recompiled'
    assert result['manifest']['fallback']==dict(interpreter=False,runtime_compilation=False)
    assert result['manifest']['presentation'] == pc.presentation()
    run([sys.executable, '-I', root/'tools/extract_assets.py', rom])
    args = ['cmake', '-S', root, '-B', root/'build', '-DCMAKE_BUILD_TYPE=Release', '-DGBA_BUILD_GPU_TESTS=ON']
    if os.environ.get('GBA_SDL3_DIR'):
        args += ['-DSDL3_DIR='+os.environ['GBA_SDL3_DIR']]
    run(args)
    run(['cmake', '--build', root/'build', '--config', 'Release', '--parallel', '2'])
    return root, binary(root, 'gba_pc')


def test_player_has_no_interpreter_and_reports_unknown_ram_without_opt_in(desktop,tmp_path):
    root,exe=desktop
    assert not (root/'build/gba_probe').exists() and not (root/'build/Release/gba_probe.exe').exists()
    assert 'contains no interpreter' in run([exe,'--interpreter'],ok=False)
    if sys.platform == 'win32':
        assert 'requires a desktop window' in run([exe,'--settings','--headless','--frames','1'],ok=False)
    error=run([exe,'--headless','--frames','8','--keys','2','--save',tmp_path/'mutation.sav'],ok=False)
    assert 'static coverage miss' in error and 'contains no interpreter' in error
    if shutil.which('nm'):
        assert 'anygba::interp::' not in run(['nm','-C',exe])


def test_live_input_arriving_during_host_work_reaches_next_frame(desktop):
    root, _ = desktop
    assert 'Live presses, releases and close events reach the next frame' in run([
        binary(root, 'gba_frame_input_tests')])


def test_desktop_finds_assets_persists_save_and_reports_software_fallback(desktop, tmp_path):
    root, exe = desktop
    env = {**os.environ, 'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy'}
    capture = tmp_path/'desktop.ppm'; script = tmp_path/'input.txt'
    script.write_text('# hold A from boot\n0 1\n')
    args = [exe, '--frames', '8', '--strict-static', '--resolution', '240x160',
            '--observe', '0x02000014', '--observe', '0x02000008', '--input-script', script]
    # No ROM/save argument; cwd is unrelated to the source project.
    report = json.loads(run([*args, '--display-capture', capture], cwd=tmp_path, env=env))
    assert not report['gpu_rendering'] and report['renderer'] == 'software'
    assert report['audio_device'] and report['audio_frames'] > 0
    assert report['drawable'] == [240, 160] and report['observed'] == [1022, 14]
    assert report['misses'] == [] and report['interpreted_cycles'] == 0
    assert capture.read_bytes() == b'P6\n240 160\n255\n'+b'\xff\x00\x00'*(240*160)
    data, _ = hardware(); save = root/'saves'/(hashlib.sha256(data).hexdigest()[:16]+'.sav')
    assert save.stat().st_size == 32768 and save.read_bytes()[0] == 0
    again = json.loads(run(args, cwd=tmp_path, env=env))
    assert save.read_bytes()[0] == 1 and again['observed'] == report['observed']
    assert pc.verify(root)['integrity_verified']
    error = run([exe, '--frames', '1', '--renderer', 'opengl'], cwd=tmp_path, env=env, ok=False)
    assert error and save.read_bytes()[0] == 1


def test_original_gpu_modes_effects_sprites_scanline_changes_and_resize(desktop, tmp_path):
    if os.environ.get('DECOMP_REQUIRE_GBA_GPU') != '1':
        pytest.skip('requires a desktop OpenGL 3.3 context; mandatory in Linux GPU CI')
    root, _ = desktop
    report=tmp_path/'gpu-scenes.json'
    result = run([binary(root, 'gba_gpu_tests'),'--report',report], env={**os.environ, 'SDL_AUDIODRIVER': 'dummy'})
    assert '18 GPU/reference scenes and drawable resize passed' in result
    data=json.loads(report.read_text())
    assert data['passed'] and data['scenes']==18 and data['reference_picture_ignored']
    assert data['resize_passed'] and data['device'] and data['renderer']=='opengl'
    assert data['bitmap_overlay_cases']==3
    assert data['resized_drawable'][0]>data['initial_drawable'][0]
    assert data['resized_drawable'][1]>data['initial_drawable'][1]
    assert all(value>0 for value in data['odd_drawable'])


def test_desktop_rejects_ambiguous_input_script_before_opening_save(desktop, tmp_path):
    _, exe = desktop
    script = tmp_path/'invalid.txt'; script.write_text('2 1\n2 0\n')
    save = tmp_path/'must-not-exist.sav'
    assert 'frames must increase' in run([exe, '--frames', '8', '--save', save,
        '--input-script', script], cwd=tmp_path, ok=False)
    assert not save.exists()


def test_cartridge_flash128_atomic_save_reload_and_rtc_protocol(desktop, tmp_path):
    root, _ = desktop
    result = run([binary(root, 'gba_cartridge_tests'), tmp_path/'flash128.sav'])
    assert 'RTC serial time/advance passed' in result
