"""Original guest programs qualify the exported PS1 hardware runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from decompnet import pc
from decompnet.psx_native import export, media
from decompnet.psx_native.extract_assets import stage
from .fixtures.psx_hardware import disc, executable


def originals(folder):
    folder.mkdir(parents=True,exist_ok=True)
    paths=[]
    for index in (1,2):
        path=folder/f'Original disc {index}.iso';path.write_bytes(disc(index));paths.append(path)
    return paths


def recipe(root,discs):
    (root/'game').mkdir(parents=True)
    (root/'game/assets.json').write_text(json.dumps(dict(discs=[
        dict(index=d['index'],kind=d['kind'],files=d['files']) for d in discs])))


def test_ordered_playlist_and_asset_hashes_preserve_existing_work(tmp_path):
    inputs=originals(tmp_path/'owned')
    playlist=tmp_path/'owned/game.m3u'
    playlist.write_text('# original ordered fixture\n'+''.join(p.name+'\n' for p in inputs),encoding='utf-8-sig')
    discs=media.prepare([playlist])
    assert [d['index'] for d in discs]==[1,2]
    assert discs[0]['image']!=discs[1]['image']
    out=tmp_path/'project';recipe(out,discs)
    with pytest.raises(ValueError,match='hash differs'):
        stage(out,list(reversed(inputs)))
    assert not (out/'assets').exists()
    stage(out,[playlist])
    assert (out/'assets/disc1'/inputs[0].name).read_bytes()==inputs[0].read_bytes()
    (out/'assets/user-data.txt').write_text('keep')
    with pytest.raises(ValueError,match='already exist'):stage(out,inputs)
    assert (out/'assets/user-data.txt').read_text()=='keep'
    with pytest.raises(pc.PCError,match='same disc'):media.prepare([inputs[0],inputs[0]])
    renamed=tmp_path/'same.iso';shutil.copyfile(inputs[0],renamed)
    with pytest.raises(pc.PCError,match='same disc content'):media.prepare([inputs[0],renamed])
    playlist.write_text('game.m3u\n')
    with pytest.raises(pc.PCError,match='nested'):media.prepare([playlist])


def test_cue_tracks_are_retained_and_checked_before_asset_staging(tmp_path):
    owned=tmp_path/'owned';owned.mkdir()
    (owned/'data.bin').write_bytes(disc())
    (owned/'audio.bin').write_bytes(bytes(2352*8))
    cue=owned/'disc.cue'
    cue.write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n'
                   'FILE "audio.bin" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n')
    discs=media.prepare([cue]);out=tmp_path/'project';recipe(out,discs)
    assert {f['name'] for f in discs[0]['files']}=={'disc.cue','data.bin','audio.bin'}
    (owned/'audio.bin').write_bytes(b'changed'.ljust(2352*8,b'\0'))
    with pytest.raises(ValueError,match='hash differs'):stage(out,[cue])
    assert not (out/'assets').exists()
    (owned/'audio.bin').write_bytes(bytes(2352*8));stage(out,[cue])
    assert (out/'assets/disc1/audio.bin').read_bytes()==bytes(2352*8)


def test_standalone_executable_stages_a_valid_bootable_disc(tmp_path):
    path=tmp_path/'original.exe';path.write_bytes(executable())
    discs=media.prepare([path]);out=tmp_path/'project';recipe(out,discs);stage(out,[path])
    wrapped=media.prepare([out/'assets/disc1/PSX.ISO'])
    assert wrapped[0]['image']==discs[0]['image']


def test_invalid_input_and_renderer_do_not_install_tools_or_publish(tmp_path,monkeypatch):
    from decompnet import toolchains
    monkeypatch.setattr(toolchains,'ensure',lambda *_a,**_k:pytest.fail('invalid input must precede tools'))
    path=tmp_path/'bad.iso';path.write_bytes(b'not a disc')
    with pytest.raises(pc.PCError):export([path],tmp_path/'output')
    with pytest.raises(pc.PCError,match='renderer'):export([path],tmp_path/'output',renderer='unknown')
    assert not (tmp_path/'output').exists()


@pytest.fixture(scope='module')
def native_project(tmp_path_factory):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('complete PS1 runtime runs in the dedicated Windows/Linux workflow')
    work=tmp_path_factory.mktemp('PS1 standalone source with spaces')
    inputs=originals(work/'owner media');root=work/'source'
    result=export(inputs,root,title='Original two-disc PS1 fixture')
    assert result['integrity_verified'] and result['presentation_declared']
    assert result['manifest']['fallback']==dict(interpreter=True,runtime_compilation=False)
    assert result['manifest']['presentation']['screen_mode']=='single'
    assert len(result['manifest']['code_generation'])==2
    # Use only the generated stdlib helper, without importing decomp.wtf.
    subprocess.run([sys.executable,'-I',str(root/'tools/extract_assets.py'),*map(str,inputs)],check=True,capture_output=True)
    command=['cmake','-S',str(root),'-B',str(root/'build'),'-DCMAKE_BUILD_TYPE=Release']
    # Local development can reuse already verified dependencies; CI starts cold.
    command+=json.loads(os.environ.get('DECOMP_PSX_CMAKE_ARGS','[]'))
    for args in (command,['cmake','--build',str(root/'build'),'--config','Release','--target','ps1_pc','--parallel','2']):
        done=subprocess.run(args,capture_output=True,text=True,timeout=1200)
        assert done.returncode==0,(done.stdout+done.stderr)[-10000:]
    exe=next(p for p in (root/'build/ps1_pc',root/'build/ps1_pc.exe',root/'build/Release/ps1_pc.exe') if p.exists())
    # Build configuration must not invalidate generated-source integrity.
    assert pc.verify(root)['integrity_verified']
    yield work,root,exe


OBSERVE=[0x80020000,0x80020100,0x8002000c,0x80020010,0x80020018,0x8002001c]


def run(project,name,*args,interp=False,driver='dummy',ok=True):
    work,root,exe=project;report=work/(name+'.json');capture=work/(name+'.ppm')
    env={**os.environ,'SDL_AUDIODRIVER':'dummy','SDL_VIDEODRIVER':driver,
         'EGL_PLATFORM':'surfaceless','LIBGL_ALWAYS_SOFTWARE':'1'}
    if interp:env['PSX_FORCE_INTERP']='1'
    command=[str(exe),'--frames','600','--report',str(report),'--capture',str(capture),
             '--memcard-dir',str(work/'shared-saves')]
    for address in OBSERVE:command+=['--observe',hex(address)]
    done=subprocess.run([*command,*map(str,args)],cwd=work,env=env,capture_output=True,text=True,timeout=90)
    (work/(name+'.log')).write_text(done.stdout+done.stderr)
    if not ok:
        assert done.returncode!=0
        return done.stdout+done.stderr
    assert done.returncode==0,(done.stdout+done.stderr)[-6000:]
    return json.loads(report.read_text()),capture


def test_native_guest_cd_audio_and_shared_memory_cards_across_disc_boots(native_project):
    first,pixels=run(native_project,'disc1','--headless','--renderer','software')
    assert first['native_dispatches']>0 and first['module_dispatches'][0]>0
    assert first['module_dispatches'][1]==0
    assert first['observed'][:4]==[1,0xd0000001,2048,0xa004]
    assert first['observed'][5]==2048
    assert first['audio_nonzero_frames']>0
    second,_=run(native_project,'disc2','--headless','--renderer','software','--disc',
        str(native_project[1]/'assets/disc2/Original disc 2.iso'))
    assert second['disc_index']==2 and second['disc_count']==2
    assert second['observed']==[2,0xd0000002,2048,0xa004,0xd0000001,2048]
    assert second['module_dispatches'][1]>0 and second['module_dispatches'][0]==0
    reference,other=run(native_project,'original-interpreted','--headless','--renderer','software',interp=True)
    assert reference['native_dispatches']==0 and reference['interpreted_instructions']>0
    assert reference['observed'][:4]==first['observed'][:4]
    assert pixels.read_bytes()==other.read_bytes()


def test_live_tray_change_preserves_resident_native_module(native_project):
    report,_=run(native_project,'tray-switch','--headless','--renderer','software','--switch-disc','450:2')
    assert report['disc_index']==2 and report['disc_sectors']==30
    assert report['observed'][:4]==[1,0xd0000001,2048,0xa004]
    assert report['module_dispatches'][0]>0 and report['module_dispatches'][1]==0


def test_automatic_fallback_and_required_gpu_failure(native_project):
    report,_=run(native_project,'automatic-fallback','--hidden-window','--renderer','auto')
    assert report['renderer']=='software' and report['software_fallback']
    assert 'OpenGL' in run(native_project,'required-gpu-failure','--hidden-window','--renderer','opengl',ok=False)


def test_actual_gpu_geometry_adapts_to_resize_and_portrait(native_project):
    if os.environ.get('DECOMP_REQUIRE_PSX_GPU')!='1':pytest.skip('GPU required on Linux qualification host')
    report,capture=run(native_project,'gpu-resize','--hidden-window','--renderer','opengl',
        '--resolution','960x720','--resize','450:1200x900',driver='offscreen')
    assert report['renderer']=='opengl' and report['device'] and not report['software_fallback']
    assert (report['drawable_width'],report['drawable_height'])==(1200,900)
    assert report['internal_scale']>=4 and report['native_dispatches']>0
    assert capture.read_bytes().startswith(b'P6\n1200 900\n255\n')
    pixels=capture.read_bytes().split(b'\n',3)[3]
    # The GPU keeps the PS1's 5-bit primitive color; this is 248, not 255.
    assert pixels.count(b'\xf8\0\0')>1000 and pixels.count(b'\0\x40\0')>1000
    portrait,_=run(native_project,'gpu-portrait','--hidden-window','--renderer','opengl',
        '--resolution','720x960',driver='offscreen')
    assert (portrait['drawable_width'],portrait['drawable_height'])==(720,960)
    assert portrait['observed'][:4]==[1,0xd0000001,2048,0xa004]
    fullscreen,_=run(native_project,'gpu-fullscreen','--renderer','opengl','--fullscreen',driver='offscreen')
    assert fullscreen['fullscreen']
    assert (fullscreen['drawable_width'],fullscreen['drawable_height'])==(fullscreen['monitor_width'],fullscreen['monitor_height'])


def test_automatic_native_platform_detection_keeps_unnamed_ds_uploads(tmp_path):
    from .fixtures.nds_native import hardware
    path=tmp_path/'game.bin';path.write_bytes(hardware()[0])
    assert pc.input_platform(path)=='nds'
    path.write_bytes(disc());assert pc.input_platform(path)=='psx'
