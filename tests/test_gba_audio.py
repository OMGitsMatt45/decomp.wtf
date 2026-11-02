"""Signal-quality and in-player checks for optional DirectSound reconstruction."""
import json
import os
from pathlib import Path
import subprocess

from decompnet.gba_native import _cmake, _source
from .test_gba_desktop import desktop, binary
from .test_gba_native import sdk, run


def test_reconstruction_preserves_pitch_gain_and_rejects_aliases(tmp_path):
    include=tmp_path/'include/anygba';include.mkdir(parents=True)
    (include/'audio_interpolator.hpp').write_text(_source('audio_interpolator.hpp'),encoding='utf-8')
    (tmp_path/'audio_settings.hpp').write_text(_source('audio_settings.hpp'),encoding='utf-8')
    (tmp_path/'audio.cpp').write_text(_source('audio_tests.cpp'),encoding='utf-8')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(AudioQuality LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        'add_executable(audio_quality audio.cpp)\n'
        'target_include_directories(audio_quality PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")\n',encoding='utf-8')
    cmake=_cmake()
    run([cmake,'-S',tmp_path,'-B',tmp_path/'build'])
    run([cmake,'--build',tmp_path/'build','--config','Release'])
    assert 'Settings round-trip preserved the save' in run([binary(tmp_path,'audio_quality'),tmp_path/'settings'])


def test_audio_modes_preserve_game_execution_and_capture_duration(desktop,tmp_path):
    _,exe=desktop
    reports=[]
    for mode in ('original','enhanced'):
        report=json.loads(run([exe,'--headless','--frames','120','--audio-mode',mode,
            '--audio-pcm',tmp_path/(mode+'.pcm'),'--observe','0x02000008']))
        assert report['audio_mode']==mode
        assert report['misses']==[] and report['interpreted_cycles']==0
        assert (tmp_path/(mode+'.pcm')).stat().st_size==report['audio_frames']*4
        reports.append(report)
    for field in ('frames','cycles','screen_sha256','audio_frames','observed'):
        assert reports[0][field]==reports[1][field],field
    assert 'audio mode must be' in run([exe,'--headless','--frames','1','--audio-mode','bad'],ok=False)


def test_audio_menu_toggle_persists_without_becoming_a_cheat(desktop,tmp_path):
    _,exe=desktop
    script=tmp_path/'menu.txt'
    script.write_text('0 0\n1 32\n2 0\n3 1\n4 0\n5 2\n6 0\n')
    save=tmp_path/'audio.sav'
    env={**os.environ,'SDL_VIDEODRIVER':'dummy','SDL_AUDIODRIVER':'dummy'}
    report=json.loads(run([exe,'--settings','--menu-input-script',script,'--frames','8',
        '--unpaced','--renderer','software','--save',save,'--audio-mode','original'],env=env))
    assert report['audio_mode']=='enhanced' and report['enabled_cheats']==0
    assert report['frames']==8 and report['menu_openings']==1
    assert report['misses']==[] and report['interpreted_cycles']==0
    sidecar=Path(str(save)+'.audio.cfg')
    assert sidecar.read_text().strip()=='enhanced=1'
    # Reading preferences must not rewrite the settings file or require desktop UI.
    before=sidecar.stat().st_mtime_ns
    again=json.loads(run([exe,'--headless','--frames','8','--save',save]))
    assert again['audio_mode']=='enhanced' and sidecar.stat().st_mtime_ns==before
