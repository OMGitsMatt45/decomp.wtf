"""Build and execute generated DS C++ with the pinned source-shipped runtime."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

import pytest

from decompnet import pc,toolchains
from decompnet.nds_native import export,SDK_COMMIT,_source
from .fixtures.nds_native import dual_cpu,hardware
from .fixtures.nds_static import simple


@pytest.fixture(scope='module')
def sdk():
    if toolchains.installed('dsr-sdk') is None:
        if os.environ.get('DECOMP_REQUIRE_DS_NATIVE')=='1':
            pytest.fail('install the pinned dsr-sdk before native qualification')
        pytest.skip('optional DS hardware runtime sources are not installed')
    return toolchains.require('dsr-sdk')


def generate(root,make):
    raw,profile=make();root.mkdir()
    rom=root/'original.nds';rom.write_bytes(raw)
    path=root/'reviewed.json';path.write_text(json.dumps(profile))
    output=root/'Standalone DS project with spaces'
    result=export(rom,output,profile=path,save_type='eeprom8k')
    assert result['integrity_verified'] and not result['gameplay_verified']
    assert result['manifest']['fallback']==dict(interpreter=False,runtime_compilation=False)
    assert result['manifest']['runtime']['revision']==SDK_COMMIT
    assert all(s['undefined_sites']==0 for s in result['manifest']['code_generation'])
    for command in ([sys.executable,'-I',str(output/'tools/extract_assets.py'),str(rom)],
                    ['cmake','-S',str(output),'-B',str(output/'build'),'-DNDS_WITH_SDL=OFF','-DCMAKE_BUILD_TYPE=Release'],
                    ['cmake','--build',str(output/'build'),'--config','Release','--parallel','2']):
        run=subprocess.run(command,capture_output=True,text=True,timeout=240)
        assert run.returncode==0,run.stdout+run.stderr
    executable=next(p for p in (output/'build/ds_pc',output/'build/ds_pc.exe',output/'build/Release/ds_pc.exe') if p.exists())
    return rom,output,executable


def execute(executable,root,*options,ok=True):
    run=subprocess.run([str(executable),'--assets',str(root/'assets'),'--headless','--frames','8',*map(str,options)],
                       capture_output=True,text=True,timeout=30)
    if ok:
        assert run.returncode==0,run.stdout+run.stderr
        return json.loads(run.stdout)
    assert run.returncode!=0
    return run.stderr


@pytest.fixture(scope='module')
def hardware_project(tmp_path_factory,sdk):
    return generate(tmp_path_factory.mktemp('hardware-runtime')/'project',hardware)


def test_full_runtime_executes_original_arm7_private_ram_and_overlay_loader(tmp_path,sdk):
    rom,root,exe=generate(tmp_path/'fixture',dual_cpu)
    result=execute(exe,root,'--save',tmp_path/'fixture.sav')
    assert result['observed']==[5,1,11,14,21,32,1]
    assert result['unimplemented_io']==0
    assert (root/'native/dsr/LICENSE').is_file() and (root/'native/dsr/DECOMP_WTF_PATCHES.md').is_file()
    assert 'OBB' in (root/'README.md').read_text()
    assert pc.verify(root)['integrity_verified']


def test_generated_guest_code_drives_video_audio_irqs_ipc_keys_and_cartridge_save(tmp_path,hardware_project):
    rom,root,exe=hardware_project
    save=tmp_path/'game.sav';capture=tmp_path/'capture';audio=tmp_path/'sound.pcm'
    inputs=tmp_path/'input.txt';inputs.write_text('\n'.join(f'{i} 1 -1 -1' for i in range(8)))
    result=execute(exe,root,'--save',save,'--capture',capture,'--audio-pcm',audio,'--input-script',inputs)
    count,keys,ipc,old,new,arm7_progress,dtcm,first,last,card_irq,*switch=result['observed']
    assert count>0 and keys==0x3fe and ipc==0x12345678 and old==255 and new==0 and arm7_progress>0
    assert dtcm==0xa55a1234
    assert first==0xd5000000 and last==0xd500007f and card_irq==0x80000
    assert switch==[22,33,255,42,63,77,255]
    assert result['unimplemented_io']==0 and result['audio_frames']>0
    for name,color in (('top',b'\xff\x00\x00'),('bottom',b'\x00\xff\x00')):
        image=(capture/(name+'.ppm')).read_bytes()
        assert image==b'P6\n256 192\n255\n'+color*(256*192)
    samples=struct.unpack('<'+'h'*(audio.stat().st_size//2),audio.read_bytes())
    assert min(samples)< -1000 and max(samples)>1000
    assert len(samples)==result['audio_frames']*2
    assert save.stat().st_size==8192 and save.read_bytes()[0]==0
    second=execute(exe,root,'--save',save)
    assert second['observed'][3:5]==[0,1] and save.read_bytes()[0]==1
    assert pc.verify(root)['integrity_verified']


def test_wrong_assets_fail_before_running_or_creating_a_save(tmp_path,hardware_project):
    _,root,exe=hardware_project
    assets=root/'assets/game.nds';before=assets.read_bytes()
    try:
        assets.write_bytes(before[:-1]+bytes([before[-1]^1]))
        assert 'SHA-256 differs' in execute(exe,root,'--save',tmp_path/'bad.sav',ok=False)
        assert not (tmp_path/'bad.sav').exists()
    finally:
        assets.write_bytes(before)


def test_cartridge_save_is_durable_before_the_process_exits(tmp_path,hardware_project):
    _,root,exe=hardware_project
    save=tmp_path/'during-play.sav'
    process=subprocess.Popen([str(exe),'--assets',str(root/'assets'),'--save',str(save),
        '--headless','--frames','1000000'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and not save.exists() and process.poll() is None:time.sleep(.02)
        assert save.exists() and process.poll() is None,'cartridge writes must persist during a running session'
    finally:
        if process.poll() is None:process.terminate()
        process.wait(timeout=15)
    assert save.stat().st_size==8192 and save.read_bytes()[0]==0
    assert execute(exe,root,'--save',save)['observed'][3:5]==[0,1]


def test_source_shipped_runtime_preserves_upstream_core_regressions(tmp_path,hardware_project):
    _,root,_=hardware_project
    runtime=root/'native/dsr/runtime'
    library=next(p for p in (root/'build/libds_runtime.a',root/'build/ds_runtime.lib',
        root/'build/Release/ds_runtime.lib') if p.is_file())
    quoted=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(RuntimeChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\n'
        f'add_executable(runtime_checks {quoted(runtime/"core/tests/core_tests.cpp")} '
        f'{quoted(runtime/"core/tests/thread_tests.cpp")} {quoted(runtime/"core/tests/abi_config_tests.cpp")})\n'
        f'target_include_directories(runtime_checks PRIVATE {quoted(runtime/"include")} {quoted(runtime/"core/include")} {quoted(runtime/"core/src")})\n'
        f'target_link_libraries(runtime_checks PRIVATE {quoted(library)} Threads::Threads)\n'
        'if(WIN32)\n target_compile_definitions(runtime_checks PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)\n'
        ' target_link_libraries(runtime_checks PRIVATE bcrypt)\nendif()\n')
    for cmd in (['cmake','-S',str(tmp_path),'-B',str(tmp_path/'build')],
                ['cmake','--build',str(tmp_path/'build'),'--config','Release','--parallel','2']):
        done=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in (tmp_path/'build/runtime_checks',tmp_path/'build/runtime_checks.exe',
                        tmp_path/'build/Release/runtime_checks.exe') if p.is_file())
    done=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
    assert done.returncode==0,done.stdout+done.stderr


def test_sdl_window_and_audio_frontend_build_and_run(tmp_path,hardware_project):
    if os.environ.get('DECOMP_REQUIRE_DS_SDL')!='1':
        pytest.skip('SDL presentation qualification runs in the dedicated native workflow')
    _,root,_=hardware_project
    build=root/'build-sdl'
    configure=['cmake','-S',str(root),'-B',str(build),'-DNDS_WITH_SDL=ON','-DCMAKE_BUILD_TYPE=Release']
    if source_dir:=os.environ.get('DECOMP_DS_SDL_SOURCE'):
        configure.append('-DFETCHCONTENT_SOURCE_DIR_SDL2='+source_dir)
    for cmd in (configure,
                ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in (build/'ds_pc',build/'ds_pc.exe',build/'Release/ds_pc.exe') if p.exists())
    done=subprocess.run([str(exe),'--assets',str(root/'assets'),'--save',str(tmp_path/'sdl.sav'),'--frames','2'],
        env={**os.environ,'SDL_VIDEODRIVER':'dummy','SDL_AUDIODRIVER':'dummy'},capture_output=True,text=True,timeout=30)
    assert done.returncode==0,done.stdout+done.stderr
    result=json.loads(done.stdout)
    assert result['frames']==2 and result['audio_frames']>0 and result['unimplemented_io']==0
    # Automatic rendering must retain a runnable original-screen project when
    # a machine cannot create GL.
    fallback=subprocess.run([str(exe),'--assets',str(root/'assets'),'--save',str(tmp_path/'fallback.sav'),
        '--frames','2','--renderer','auto'],
        env={**os.environ,'SDL_VIDEODRIVER':'dummy','SDL_AUDIODRIVER':'dummy'},capture_output=True,text=True,timeout=30)
    assert fallback.returncode==0,fallback.stdout+fallback.stderr
    report=json.loads(fallback.stdout)
    assert report['video']['renderer']=='software'
    assert 'OpenGL unavailable; using software screens' in fallback.stderr



def test_unsupported_code_does_not_publish_an_incomplete_repository(tmp_path,sdk):
    raw,profile=simple(struct.pack('<I',0xe7f000f0))  # undefined ARM instruction
    profile.pop('save_region')
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(pc.PCError,match='unsupported instruction sites'):
        export(rom,tmp_path/'out',profile=path)
    assert not (tmp_path/'out').exists()


def test_mismatched_shared_stack_frame_does_not_hide_unsupported_code(tmp_path,sdk):
    import hashlib
    raw,profile=hardware();raw=bytearray(raw)
    symbols=json.loads((Path(__file__).parent/'fixtures/nds-hardware/program.json').read_text())['arm9']['symbols']
    offset,_,base,_=struct.unpack_from('<4I',raw,0x20)
    at=offset+symbols['shared_start']-base+2
    allocation=struct.unpack_from('<H',raw,at)[0]
    assert allocation&0xff80==0xb080
    struct.pack_into('<H',raw,at,allocation+1)
    profile['input_sha256']=hashlib.sha256(raw).hexdigest()
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(pc.PCError,match='unsupported instruction sites'):
        export(rom,tmp_path/'out',profile=path)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('cpu,stack',[('arm9',0x0380ff00),('arm7',0x00803f00)])
def test_reviewed_stacks_cannot_use_the_other_processors_private_ram(tmp_path,sdk,cpu,stack):
    raw,profile=hardware();profile['processors'][cpu]['stack']=stack
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    path=tmp_path/'profile.json';path.write_text(json.dumps(profile))
    with pytest.raises(pc.PCError,match='accessible to that processor'):
        export(rom,tmp_path/'out',profile=path)
    assert not (tmp_path/'out').exists() and rom.read_bytes()==raw


def test_reviewed_arm9_stack_can_use_its_default_dtcm(tmp_path):
    from decompnet.nds_native import _reviewed
    raw,profile=hardware();profile['processors']['arm9']['stack']=0x00803f00
    _,facts=_reviewed(raw,profile,tmp_path)
    assert facts['processors']['arm9']['stack']==0x00803f00


def test_relative_bios_input_remains_accessible_from_analysis_working_directory(tmp_path,monkeypatch):
    from decompnet.nds_native import _prepare
    raw,_=hardware();rom=tmp_path/'original.nds';rom.write_bytes(raw)
    bios=tmp_path/'decoder-input.bin';bios.write_bytes(bytes(16*1024))  # synthetic size fixture, never executed
    monkeypatch.chdir(tmp_path)
    prepared=_prepare('original.nds',arm7_bios='decoder-input.bin')
    work=tmp_path/'analysis';work.mkdir();monkeypatch.chdir(work)
    assert prepared['bios'].is_absolute() and prepared['bios'].read_bytes()==bios.read_bytes()


@pytest.mark.parametrize('kind',['decrypted','wrong-size','missing'])
def test_invalid_bios_configuration_fails_before_tool_installation(tmp_path,monkeypatch,kind):
    raw,_=hardware();rom=tmp_path/'original.nds';rom.write_bytes(raw)
    bios=tmp_path/'decoder-input.bin'
    if kind!='missing':bios.write_bytes(bytes(4096 if kind=='wrong-size' else 16*1024))
    monkeypatch.setattr(toolchains,'ensure',lambda *_a,**_k:pytest.fail('invalid input must precede tool installation'))
    with pytest.raises(pc.PCError,match='decrypted input' if kind=='decrypted' else '16 KiB'):
        export(rom,tmp_path/'output',arm7_bios=bios,input_format='decrypted' if kind=='decrypted' else 'auto')
    assert not (tmp_path/'output').exists() and rom.read_bytes()==raw


@pytest.mark.parametrize('renderer,mode',[('unknown','dual'),('opengl','unknown'),('software','unified')])
def test_invalid_video_options_fail_before_tool_installation(tmp_path,monkeypatch,renderer,mode):
    raw,_=hardware();rom=tmp_path/'original.nds';rom.write_bytes(raw)
    monkeypatch.setattr(toolchains,'ensure',lambda *_a,**_k:pytest.fail('invalid presentation must precede tool installation'))
    with pytest.raises(pc.PCError,match='renderer|screen mode|requires OpenGL'):
        export(rom,tmp_path/'output',renderer=renderer,screen_mode=mode)
    assert not (tmp_path/'output').exists()


def test_hash_implementation_matches_standard_vectors_and_padding_boundaries(tmp_path):
    # The generated host uses this digest before touching a cartridge/save.
    (tmp_path/'hash.hpp').write_text(_source('hash.hpp'))
    (tmp_path/'main.cpp').write_text('#include "hash.hpp"\n#include <iostream>\nint main(int n,char** a){std::cout<<input_sha256(a[1]);}\n')
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(HashTest LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nadd_executable(hash_test main.cpp)\n')
    for cmd in (['cmake','-S',str(tmp_path),'-B',str(tmp_path/'build')],
                ['cmake','--build',str(tmp_path/'build'),'--config','Release']):
        done=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in (tmp_path/'build/hash_test',tmp_path/'build/hash_test.exe',tmp_path/'build/Release/hash_test.exe') if p.exists())
    for size in (0,1,55,56,63,64,65,127,128,129,1024,200001):
        data=bytes((i*37)%256 for i in range(size));path=tmp_path/'vector';path.write_bytes(data)
        done=subprocess.run([str(exe),str(path)],capture_output=True,text=True,check=True)
        assert done.stdout==hashlib.sha256(data).hexdigest()


def test_standalone_asset_staging_applies_private_decoding_without_external_tools(tmp_path):
    root=tmp_path/'generated';(root/'game').mkdir(parents=True);(root/'tools').mkdir()
    original=bytes(range(256))*4
    decoded=bytearray(original);decoded[64:72]=b'own code'
    identity=dict(sha256=hashlib.sha256(original).hexdigest(),size=len(original),
        asset_sha256=hashlib.sha256(decoded).hexdigest(),asset_patches=[dict(offset=64,hex=b'own code'.hex())])
    (root/'game/input.json').write_text(json.dumps(identity))
    (root/'tools/extract_assets.py').write_text(_source('extract.py'))
    rom=tmp_path/'original.nds';rom.write_bytes(original)
    command=[sys.executable,'-I',str(root/'tools/extract_assets.py'),str(rom)]
    run=subprocess.run(command,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert (root/'assets/game.nds').read_bytes()==decoded and rom.read_bytes()==original
    # Failed decoding never replaces the previous complete assets.
    identity['asset_sha256']='0'*64
    (root/'game/input.json').write_text(json.dumps(identity))
    assert subprocess.run(command,capture_output=True).returncode!=0
    assert (root/'assets/game.nds').read_bytes()==decoded
    assert not (root/'assets/game.tmp').exists()
