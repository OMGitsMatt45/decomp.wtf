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
        boot='SLUSP314.15' if index==1 else 'SLUS_314.16'
        path=folder/f'Original disc {index}.iso';path.write_bytes(disc(index,boot=boot));paths.append(path)
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


@pytest.mark.parametrize('compressed',[False,True])
def test_original_chd_program_and_container_are_retained(tmp_path,compressed):
    from .test_psx_media import original_chd
    from .test_psx_disc import fixture
    path=tmp_path/'original.chd';raw=original_chd(fixture(2448,24),compressed=compressed)
    path.write_bytes(raw);discs=media.prepare([path]);out=tmp_path/'project';recipe(out,discs)
    assert discs[0]['image'].startswith(b'PS-X EXE')
    stage(out,[path]);assert (out/'assets/disc1/original.chd').read_bytes()==raw


def test_imported_disc_retains_reviewed_module_bytes_and_rejects_changed_layout(tmp_path):
    from decompnet.rom import detect,psx_media
    path=tmp_path/'original.iso';path.write_bytes(disc())
    picked=detect.identify(path);root=tmp_path/'imported';root.mkdir()
    psx_media.snapshot(path,picked,root)
    layout={**picked.disc,'file':'original-disc.bin'}
    # A small original raw module inside SAMPLE.BIN has a reviewed load address.
    file=next(f for f in layout['files'] if f['path']=='SAMPLE.BIN')
    import hashlib
    raw=path.read_bytes()[file['lba']*2048:file['lba']*2048+16]
    mapping=dict(segment='original_overlay',lba=file['lba'],size=len(raw),load=0x80030000,
        sha256=hashlib.sha256(raw).hexdigest(),code_at=0,path='SAMPLE.BIN')
    layout['maps'].append(mapping)
    project=dict(root=str(root),psx_disc=layout,psx_modules={})
    result=media.project_input(project,1)
    assert len(result['modules'])==1 and result['modules'][0]['image'][2048:]==raw
    assert result['modules'][0]['info']['entrypoint']==0x80030000
    mapping['sha256']='0'*64
    with pytest.raises(pc.PCError,match='module hash differs'):media.project_input(project,1)


def test_existing_export_destination_preserves_authored_sources(tmp_path,monkeypatch):
    path=tmp_path/'original.iso';path.write_bytes(disc())
    output=tmp_path/'project';output.mkdir();(output/'user.cpp').write_text('my source')
    monkeypatch.setattr('decompnet.psx_native._sdk',lambda:pytest.fail('existing output must precede SDK setup'))
    with pytest.raises(pc.PCError,match='existing work'):export([path],output)
    assert (output/'user.cpp').read_text()=='my source'


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
    assert result['manifest']['fallback']==dict(interpreter=False,runtime_compilation=False)
    assert result['manifest']['execution_model']=='static-recompiled'
    assert result['manifest']['presentation']['screen_mode']=='single'
    assert len(result['manifest']['code_generation'])==2
    # Use only the generated stdlib helper, without importing decomp.wtf.
    subprocess.run([sys.executable,'-I',str(root/'tools/extract_assets.py'),*map(str,inputs)],check=True,capture_output=True)
    build=Path(os.environ.get('DECOMP_PSX_BUILD_ROOT',root/'build'))
    command=['cmake','-S',str(root),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DPS1_BUILD_REFERENCE=ON']
    # Local development can reuse already verified dependencies; CI starts cold.
    command+=json.loads(os.environ.get('DECOMP_PSX_CMAKE_ARGS','[]'))
    for args in (command,['cmake','--build',str(build),'--config','Release','--target','ps1_pc','ps1_probe','--parallel','2']):
        done=subprocess.run(args,capture_output=True,text=True,timeout=1200)
        assert done.returncode==0,(done.stdout+done.stderr)[-10000:]
    exe=next(p for p in (build/'ps1_pc',build/'ps1_pc.exe',build/'Release/ps1_pc.exe') if p.exists())
    # Build configuration must not invalidate generated-source integrity.
    assert pc.verify(root)['integrity_verified']
    yield work,root,exe


OBSERVE=[0x80020000,0x80020100,0x8002000c,0x80020010,0x80020018,0x8002001c]


def run(project,name,*args,interp=False,driver='dummy',ok=True,frames=600):
    work,root,exe=project;report=work/(name+'.json');capture=work/(name+'.ppm')
    if interp:exe=exe.with_name('ps1_probe'+exe.suffix)
    env={**os.environ,'SDL_AUDIODRIVER':'dummy','SDL_VIDEODRIVER':driver,
         'EGL_PLATFORM':'surfaceless','LIBGL_ALWAYS_SOFTWARE':'1',
         'DECOMP_PSX_TRACE':'1','PSX_FRAME_REPORT_MS':'1000'}
    if interp:env['PSX_FORCE_INTERP']='1'
    command=[str(exe),'--game',str(root/'game.toml'),'--frames',str(frames),'--report',str(report),'--capture',str(capture),
             '--memcard-dir',str(work/'shared-saves')]
    for address in OBSERVE:command+=['--observe',hex(address)]
    timeout=180 if interp else 90
    try:done=subprocess.run([*command,*map(str,args)],cwd=work,env=env,capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def decoded(value):return value.decode('utf-8','replace') if isinstance(value,bytes) else value or ''
        output=decoded(error.stdout)+decoded(error.stderr)
        (work/(name+'.log')).write_text(output,encoding='utf-8')
        pytest.fail('runtime timed out:\n'+output[-8000:])
    (work/(name+'.log')).write_text(done.stdout+done.stderr)
    if not ok:
        assert done.returncode!=0
        return done.stdout+done.stderr
    assert done.returncode==0,(done.stdout+done.stderr)[-6000:]
    return json.loads(report.read_text()),capture


def test_native_guest_cd_audio_and_shared_memory_cards_across_disc_boots(native_project):
    # The guest finishes CD/card operations before frame 300. Compare both
    # execution modes at 360; a longer run only interprets the busy-wait loop.
    # The separate reference gets 180 seconds: Windows reached frame 353 at
    # the former 90-second limit, after all guest operations had completed.
    first,pixels=run(native_project,'disc1','--headless','--renderer','software',frames=360)
    assert 'does not contain the expected game ID' not in (native_project[0]/'disc1.log').read_text()
    assert first['native_dispatches']>0 and first['module_dispatches'][0]>0
    assert first['interpreted_instructions']==0 and first['coverage_misses']==0
    assert first['module_dispatches'][1]==0
    assert first['observed'][:4]==[1,0xd0000001,2048,0xa004]
    assert first['observed'][5]==2048
    assert first['audio_nonzero_frames']>0
    second,second_pixels=run(native_project,'disc2','--headless','--renderer','software','--disc',
        str(native_project[1]/'assets/disc2/Original disc 2.iso'),frames=360)
    assert second['disc_index']==2 and second['disc_count']==2
    assert second['interpreted_instructions']==0 and second['coverage_misses']==0
    assert second['observed']==[2,0xd0000002,2048,0xa004,0xd0000001,2048]
    assert second['module_dispatches'][1]>0
    # The original helper bytes are identical on both discs and may safely
    # reuse the first module. Disc-specific code must produce disc 2's marker.
    assert second['depth24']
    assert second['depth24_trailing_margin']==0
    header=second_pixels.read_bytes().split(b'\n',3)
    assert header[:3]==[b'P6',b'320 240',b'255']
    assert header[3][(120*320+319)*3:(120*320+320)*3]==b'\xff\0\0'
    reference,other=run(native_project,'original-interpreted','--headless','--renderer','software',interp=True,frames=360)
    assert reference['native_dispatches']==0 and reference['interpreted_instructions']>0
    assert reference['execution_model']=='reference'
    assert reference['observed'][:4]==first['observed'][:4]
    assert pixels.read_bytes()==other.read_bytes()


def test_native_player_rejects_uncompiled_bytes_and_records_the_gap(native_project):
    from decompnet.psx_native.extract_assets import iso
    work,root,exe=native_project
    image=bytearray(executable())
    image[2048]^=1  # Original input's first LUI differs; no matching native CFG.
    path=work/'changed-program.iso';path.write_bytes(iso(bytes(image)))
    output=run(native_project,'uncompiled-entry','--headless','--renderer','software','--disc',path,ok=False,frames=360)
    assert 'missing native PS1 code' in output
    report=json.loads((work/'uncompiled-entry.json').read_text())
    assert report['coverage_misses']==1 and report['coverage_pc']==0x80010000
    assert report['interpreted_instructions']==0
    probe=exe.with_name('ps1_probe'+exe.suffix)
    native_contract=json.loads(exe.with_name(exe.stem+'.execution.json').read_text())
    reference_contract=json.loads(probe.with_name(probe.stem+'.execution.json').read_text())
    assert native_contract['identity']!=reference_contract['identity']
    if os.name!='nt' and shutil.which('nm'):
        symbols=subprocess.run(['nm','-a',str(exe)],capture_output=True,text=True,check=True).stdout
        assert 'exec_one_fetched_inner' not in symbols


def test_live_tray_change_preserves_resident_native_module(native_project):
    report,_=run(native_project,'tray-switch','--headless','--renderer','software',
        '--disc',native_project[1]/'assets/disc1/Original disc 1.iso','--switch-disc','450:2')
    assert report['disc_index']==2 and report['disc_sectors']==30
    assert report['observed'][:4]==[1,0xd0000001,2048,0xa004]
    assert report['module_dispatches'][0]>0 and report['module_dispatches'][1]==0
    restarted,_=run(native_project,'tray-restarted','--headless','--renderer','software',frames=360)
    assert restarted['disc_index']==2 and restarted['observed'][0]==2
    assert restarted['module_dispatches'][1]>0 and restarted['interpreted_instructions']==0


def test_standalone_executable_envelope_boots_through_real_bios(native_project):
    from decompnet.psx_native.extract_assets import iso
    path=native_project[0]/'standalone.iso';path.write_bytes(iso(executable()))
    report,_=run(native_project,'standalone-executable','--headless','--renderer','software','--disc',path)
    assert report['observed'][0]==1 and report['native_dispatches']>0


def test_scripted_input_reaches_the_actual_offline_pad_sampler(native_project):
    script=native_project[0]/'original-input.txt'
    script.write_text('# held masks\n0 0xffff\n100 0xbfff\n400 0xffef\n500 0xffff\n')
    report,_=run(native_project,'scripted-cross','--headless','--renderer','software',
        '--input-script',script,frames=360)
    assert report['scripted_input'] and report['pad0_connected']==1
    assert report['pad0_buttons']==0xbfff
    assert report['interpreted_instructions']==0 and report['coverage_misses']==0
    script.write_text('0 0xbfff\n300 LIVE\n')
    report,_=run(native_project,'scripted-handoff','--headless','--renderer','software',
        '--input-script',script,frames=360)
    assert report['pad0_buttons']==0xffff
    assert report['interpreted_instructions']==0 and report['coverage_misses']==0


@pytest.mark.parametrize('library_load,resident',[(0x80010000,True),(0x80100000,False)])
def test_overlay_calls_seed_unreferenced_resident_varargs_entry(native_project,tmp_path,library_load,resident):
    import struct
    from decompnet.psx_native import _sdk,_recompiler,_run,codegen
    sdk=_sdk();emitter=_recompiler(sdk);target=library_load+0x200
    def image(load,words,leaf=False):
        payload=bytearray(2048);struct.pack_into('<'+'I'*len(words),payload,0,*words)
        if leaf:
            # A valid varargs-style entry has no initial stack adjustment and
            # no caller in its own resident image, like the missed retail case.
            struct.pack_into('<6I',payload,0x200,0xafa50004,0xafa60008,0xafa7000c,
                             0x24020007,0x03e00008,0)
        header=bytearray(2048);header[:8]=b'PS-X EXE'
        struct.pack_into('<4I',header,0x10,load,0,load,len(payload))
        return bytes(header+payload)
    boot=dict(index=1,module_index=1,boot='LIBRARY.EXE',resident_boot=resident,
        image=image(library_load,[0x1000ffff,0],True),info=dict(load=library_load,entrypoint=library_load))
    overlay=dict(index=1,module_index=2,boot='OVERLAY.EXE',
        image=image(0x80130000,[0x0c000000|((target>>2)&0x03ffffff),0,0x1000ffff,0]),
        info=dict(load=0x80130000,entrypoint=0x80130000))
    resident=tmp_path/'disc1';nested=resident/'module1'
    modules=[codegen.module(emitter,boot,resident,_run,sdk),
             codegen.module(emitter,overlay,nested,_run,sdk)]
    modules[0]['origins']=[dict(disc=1),dict(disc=2)]
    assert target not in modules[0]['entries'] and target in modules[1]['external_calls']
    overlay_hash=modules[1]['dispatch_sha256']
    report=codegen.close_resident_calls(emitter,[(boot,resident),(overlay,nested)],modules,_run,sdk)
    assert target in modules[0]['entries'] and report[0]['uncompiled_calls']==[]
    assert modules[0]['origins']==[dict(disc=1),dict(disc=2)]
    assert modules[1]['dispatch_sha256']==overlay_hash and (nested/'OVERLAY.EXE_dispatch.c').is_file()


def test_automatic_fallback_and_required_gpu_failure(native_project):
    report,_=run(native_project,'automatic-fallback','--hidden-window','--renderer','auto')
    assert report['renderer']=='software' and report['software_fallback']
    assert 'OpenGL' in run(native_project,'required-gpu-failure','--hidden-window','--renderer','opengl',ok=False)


def test_bounded_window_logs_disc_warning_and_finishes(native_project):
    config=native_project[1]/'game.toml'
    original=config.read_text()
    assert 'SLUS-31415' in original
    try:
        config.write_text(original.replace('SLUS-31415','SLUS-99999'))
        # Earlier tray changes deliberately persist the selected disc. This
        # warning concerns disc 1's edited ID, so select that media explicitly.
        report,_=run(native_project,'bounded-warning','--game',config,'--renderer','software',
            '--disc',native_project[1]/'assets/disc1/Original disc 1.iso',frames=2)
    finally:
        config.write_text(original)
    assert report['frames']==2
    assert 'Disc Image Warning' in (native_project[0]/'bounded-warning.log').read_text()


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
    video,capture=run(native_project,'gpu-rgb888','--hidden-window','--renderer','opengl',
        '--resolution','960x720','--disc',str(native_project[1]/'assets/disc2/Original disc 2.iso'),driver='offscreen')
    assert video['depth24'] and video['renderer']=='opengl'
    pixels=capture.read_bytes().split(b'\n',3)[3]
    assert pixels.count(b'\xff\0\0')>300000


def test_automatic_native_platform_detection_keeps_unnamed_ds_uploads(tmp_path):
    from .fixtures.nds_native import hardware
    path=tmp_path/'game.bin';path.write_bytes(hardware()[0])
    assert pc.input_platform(path)=='nds'
    path.write_bytes(disc());assert pc.input_platform(path)=='psx'


def test_short_keyboard_pulses_reach_one_pad_sample_and_respect_suppression(native_project,tmp_path):
    from decompnet.psx_native import _sdk,_run,runtime_patch
    sdk=_sdk()
    source=sdk/'runtime/src/psx_keybinds.c';header=sdk/'runtime/include/psx_keybinds.h'
    body,api=runtime_patch.keyboard_sampling(source.read_text(),header.read_text())
    (tmp_path/'psx_keybinds.c').write_text(body);(tmp_path/'psx_keybinds.h').write_text(api)
    (tmp_path/'runner.c').write_text(r'''
#include "psx_keybinds.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"failed line %d\n",__LINE__);return 1;}}while(0)
int main(void){
    uint8_t keys[SDL_NUM_SCANCODES]={0},sticks[4]={128,128,128,128};
    CHECK(psx_keybinds_pad_word(keys,1)==0xffff);
    /* KEYDOWN followed by KEYUP before a guest frame still arrives. */
    decomp_keybinds_note_keydown(SDL_SCANCODE_X);decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
    CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
    decomp_keybinds_begin_sample();CHECK(psx_keybinds_pad_word(keys,1)==0xffff);
    keys[SDL_SCANCODE_X]=1;decomp_keybinds_note_keydown(SDL_SCANCODE_X);
    decomp_keybinds_begin_sample();decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
    keys[SDL_SCANCODE_X]=0;decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_pad_word(keys,1)==0xffff);
    decomp_keybinds_note_keydown(SDL_SCANCODE_UP);decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_dpad_active(keys,1));psx_keybinds_sticks(keys,1,sticks);
    CHECK(sticks[1]==0);decomp_keybinds_begin_sample();
    CHECK(!psx_keybinds_dpad_active(keys,1));
    /* Consuming P1's source must not resurrect it after KEYUP, or clear P2. */
    decomp_keybinds_note_keydown(SDL_SCANCODE_X);
    psx_keybinds_suppress_control(1,SDL_SCANCODE_X);
    psx_keybinds_release_control(1,SDL_SCANCODE_X);decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_pad_word(keys,1)==0xffff&&psx_keybinds_pad_word(keys,2)==0xbfff);
    decomp_keybinds_clear_pulses();CHECK(psx_keybinds_pad_word(keys,2)==0xffff);
    psx_keybinds_set_button(1,PSX_KB_CROSS,SDL_SCANCODE_C);
    decomp_keybinds_note_keydown(SDL_SCANCODE_C);decomp_keybinds_begin_sample();
    CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
    decomp_keybinds_clear_pulses();
    decomp_keybinds_note_keydown(SDL_SCANCODE_UNKNOWN);
    decomp_keybinds_note_keydown((SDL_Scancode)-1);
    decomp_keybinds_note_keydown((SDL_Scancode)SDL_NUM_SCANCODES);
    decomp_keybinds_begin_sample();CHECK(psx_keybinds_pad_word(keys,1)==0xffff);
    /* Optional automation pulses span slow guest polling loops exactly. */
    decomp_keybinds_set_tap_frames(6);
    decomp_keybinds_set_tap_frames(0);decomp_keybinds_set_tap_frames(31);
    decomp_keybinds_note_keydown(SDL_SCANCODE_C);
    for(int frame=0;frame<6;frame++) {
        decomp_keybinds_begin_sample();CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
        CHECK(psx_keybinds_pad_word(keys,1)==0xbfff);
    }
    decomp_keybinds_begin_sample();CHECK(psx_keybinds_pad_word(keys,1)==0xffff);
    decomp_keybinds_note_keydown(SDL_SCANCODE_C);decomp_keybinds_note_keydown(SDL_SCANCODE_X);
    decomp_keybinds_begin_sample();
    psx_keybinds_suppress_control(1,SDL_SCANCODE_C);
    CHECK(psx_keybinds_pad_word(keys,1)==0xffff&&psx_keybinds_pad_word(keys,2)==0xbfff);
    decomp_keybinds_clear_pulses();
    return 0;
}''')
    q=lambda value:json.dumps(value.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(KeyboardPulse LANGUAGES C)\n'
        'set(CMAKE_C_STANDARD 11)\nfind_package(SDL3 REQUIRED CONFIG PATHS '+
        q(native_project[1]/'build/_deps/sdl3-build')+' NO_DEFAULT_PATH)\n'
        'add_executable(checks runner.c psx_keybinds.c)\n'
        'target_include_directories(checks PRIVATE . '+q(sdk/'runtime/include')+')\n'
        'target_compile_definitions(checks PRIVATE PSX_SDL3)\n'
        'target_link_libraries(checks PRIVATE SDL3::SDL3)\n')
    _run(['cmake','-S',tmp_path,'-B',tmp_path/'build'],'Configure real keyboard sampler regression')
    _run(['cmake','--build',tmp_path/'build','--config','Release','--parallel','2'],'Build real keyboard sampler regression')
    binary=next(p for p in (tmp_path/'build/checks',tmp_path/'build/Release/checks.exe') if p.is_file())
    _run([binary],'Check quick keyboard taps through actual pad folding')
