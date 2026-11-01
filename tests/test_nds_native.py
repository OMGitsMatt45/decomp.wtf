"""Build and execute generated DS C++ with the pinned source-shipped runtime."""
import hashlib
from datetime import datetime, timezone
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
from .fixtures.nds_native import dual_cpu,hardware,mixed_arm_switch,rtc
from .fixtures.nds_static import simple


@pytest.fixture(scope='module')
def sdk():
    if toolchains.installed('dsr-sdk') is None:
        if os.environ.get('DECOMP_REQUIRE_DS_NATIVE')=='1':
            pytest.fail('install the pinned dsr-sdk before native qualification')
        pytest.skip('optional DS hardware runtime sources are not installed')
    return toolchains.require('dsr-sdk')


def generate(root,make,*,cmake_options=()):
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
                    ['cmake','-S',str(output),'-B',str(output/'build'),'-DNDS_WITH_SDL=OFF','-DCMAKE_BUILD_TYPE=Release',*cmake_options],
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


@pytest.mark.parametrize('dependency',['guest_work_patch.py','audio_queue.hpp','audio_patch.py','widescreen_patch.py','dynamic_layout.hpp','cheats.hpp','settings.hpp','input.hpp','keyboard.hpp','project_hooks.hpp'])
def test_backend_revision_changes_with_emitted_runtime_and_host_dependencies(monkeypatch,dependency):
    from decompnet import nds_native
    source=nds_native._source
    before=nds_native.revision()
    monkeypatch.setattr(nds_native,'_source',lambda name:
        source(name)+'\n// changed export dependency\n' if name==dependency else source(name))
    assert nds_native.revision()!=before


def test_analysis_retries_when_decoder_fails_before_creating_config(tmp_path,monkeypatch):
    from decompnet import nds_native
    monkeypatch.setattr(toolchains,'ensure',lambda *a,**k:tmp_path)
    monkeypatch.setattr(toolchains,'binary',lambda *a,**k:tmp_path/'dsd')
    attempts=[]
    def run(command,cwd,what):
        if what!='DS code analysis':return
        attempts.append(command)
        if len(attempts)==1:raise pc.PCError('call leads to no function')
        assert '--allow-unknown-function-calls' in command
        raise pc.PCError('retried decoder diagnostic')
    monkeypatch.setattr(nds_native,'_run',run)
    with pytest.raises(pc.PCError,match='retried decoder diagnostic'):
        nds_native._analyze(tmp_path/'original.nds',tmp_path,tmp_path,None,'auto',None)
    assert len(attempts)==2 and not (tmp_path/'config').exists()


def test_conditional_irq_scan_derives_only_a_balanced_ready_loop(sdk):
    import capstone
    import importlib.util
    from decompnet.nds_native.abi_patch import install
    name='decompnet._original_abi_scan_test'
    spec=importlib.util.spec_from_file_location(name,sdk/'tools/derive_abi_config.py')
    analyzer=importlib.util.module_from_spec(spec);sys.modules[name]=analyzer
    spec.loader.exec_module(analyzer)
    def load(dst,base,offset=0):return 0xe5900000|base<<16|dst<<12|offset
    def store(src,offset):return 0xe58c0000|src<<12|offset
    words=[load(12,15),0xe3a03000,load(12,12),0xe3a02009,
           store(2,0x90),store(3,0xa0),store(3,0xa4),load(0,12,0xa8),store(3,0xa8),
           load(12,15),store(3,0x10),store(3,0x14),load(12,15),0xe1dc11b8,
           0xe28c2020,0xe3510000,0x11d109b0,0x13500009,0x15911094,0x1afffffa,
           load(3,12,0x24),0xe1a0e00f,0xe12fff13,store(1,0x1c)]
    literals=len(words);words.extend([0x02104000,0x02105000])
    for index,literal in ((0,literals),(9,literals),(12,literals+1)):
        words[index]=load(12,15,(literal-index-2)*4)
    def function(values):
        image=struct.pack('<'+'I'*len(values),*values)
        decoder=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM);decoder.detail=True
        return analyzer.Function(0x02010000,-1,0x02010000,image,list(decoder.disasm(image,0x02010000)))
    assert analyzer.irq_layout(function(words)) is None
    install(analyzer);install(analyzer)
    result=analyzer.irq_layout(function(words))
    assert result['ready_state']==9 and result['state_offset']==0x90
    assert result['alarm_queue']==0x02104000 and result['thread_info']==0x02105000
    assert result['list_next_offset']==0x94 and result['info_active_offset']==0x1c
    for index,replacement in ((17,0x13500008),(18,0x05911094),(19,0x1afffff9)):
        wrong=words.copy();wrong[index]=replacement
        assert analyzer.irq_layout(function(wrong)) is None


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


def test_source_hashes_survive_windows_git_checkout(tmp_path,sdk):
    raw,profile=dual_cpu()
    rom=tmp_path/'original.nds';rom.write_bytes(raw)
    reviewed=tmp_path/'reviewed.json';reviewed.write_text(json.dumps(profile))
    root=tmp_path/'output'
    export(rom,root,profile=reviewed,save_type='eeprom8k')
    manifest=(root/'pc-project.json').read_bytes()
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-c','core.autocrlf=true','add','.'],cwd=root,check=True,capture_output=True)
    for name in json.loads(manifest)['files']:
        (root/name).unlink()
    (root/'pc-project.json').unlink()
    subprocess.run(['git','-c','core.autocrlf=true','checkout-index','-a','-f'],cwd=root,check=True)
    assert (root/'pc-project.json').read_bytes()==manifest
    assert pc.verify(root)['integrity_verified']


def test_guest_rtc_defaults_to_local_date_and_accepts_explicit_fixed_utc(tmp_path,sdk):
    _,root,exe=generate(tmp_path/'clock',rtc)
    bcd=lambda value:(value//10)*16+value%10
    date=lambda now:[bcd(now.year%100),bcd(now.month),bcd(now.day),(now.weekday()+1)%7]
    before=datetime.now()
    local=execute(exe,root,'--save',tmp_path/'local.sav')
    after=datetime.now()
    assert local['rtc']==dict(mode='local',start_unix=None)
    assert local['observed'][:4] in (date(before),date(after))
    for epoch in (1704067200,946684800,4102444799):
        fixed=execute(exe,root,'--save',tmp_path/'fixed.sav','--rtc-start',epoch)
        assert fixed['rtc']==dict(mode='fixed-utc',start_unix=epoch)
        assert fixed['observed'][:4]==date(datetime.fromtimestamp(epoch,timezone.utc))
        assert fixed['unimplemented_io']==0
    for epoch in ('-1','bad','946684799','4102444800'):
        assert execute(exe,root,'--save',tmp_path/'bad-clock.sav','--rtc-start',epoch,ok=False)
        assert not (tmp_path/'bad-clock.sav').exists()


def test_generated_guest_code_drives_video_audio_irqs_ipc_keys_and_cartridge_save(tmp_path,hardware_project):
    rom,root,exe=hardware_project
    save=tmp_path/'game.sav';capture=tmp_path/'capture';audio=tmp_path/'sound.pcm'
    inputs=tmp_path/'input.txt';inputs.write_text('\n'.join(f'{i} 1 -1 -1' for i in range(8)))
    result=execute(exe,root,'--save',save,'--capture',capture,'--audio-pcm',audio,'--input-script',inputs)
    count,keys,ipc,old,new,arm7_progress,dtcm,first,last,card_irq,*switch=result['observed'][:17]
    assert count>0 and keys==0x3fe and ipc==0x12345678 and old==255 and new==0 and arm7_progress>0
    assert dtcm==0xa55a1234
    assert first==0xd5000000 and last==0xd500007f and card_irq==0x80000
    assert switch==[22,33,255,42,63,77,255]
    assert result['observed'][17:]==[42,90,0,0,7,4]  # result, saved r4, SP delta, unused, inline result, probes
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


@pytest.mark.parametrize('wide',[False,True])
def test_arm_switch_keeps_direct_returns_and_proven_large_bounds(tmp_path,sdk,wide):
    _,root,exe=generate(tmp_path/'mixed-switch',lambda:mixed_arm_switch(wide=wide))
    result=execute(exe,root,'--save',tmp_path/'switch.sav')
    assert result['observed']==([77,299,300] if wide else [11,1,22,3])
    assert result['unimplemented_io']==0


def test_wrong_assets_fail_before_running_or_creating_a_save(tmp_path,hardware_project):
    _,root,exe=hardware_project
    assets=root/'assets/game.nds';before=assets.read_bytes()
    try:
        assets.write_bytes(before[:-1]+bytes([before[-1]^1]))
        assert 'SHA-256 differs' in execute(exe,root,'--save',tmp_path/'bad.sav',ok=False)
        assert not (tmp_path/'bad.sav').exists()
    finally:
        assets.write_bytes(before)


def test_opt_in_memory_capture_contains_graphics_state(tmp_path,hardware_project):
    _,root,exe=hardware_project
    capture=tmp_path/'memory'
    result=execute(exe,root,'--save',tmp_path/'memory.sav','--dump-memory',capture)
    assert result['unimplemented_io']==0
    assert (capture/'main.bin').stat().st_size==0x400000
    assert (capture/'oam.bin').stat().st_size==0x800
    assert (capture/'palettes.bin').stat().st_size==0x800
    assert sum((capture/f'vram-{bank}.bin').stat().st_size for bank in 'ABCDEFGHI')==0xa4000
    video=json.loads((capture/'video.json').read_text())
    assert len(video['engines'])==2 and len(video['vramcnt'])==9
    assert all(len(engine)>=0x50//4 for engine in video['engines'])
    geometry=json.loads((capture/'geometry.json').read_text())
    assert isinstance(geometry['vertices'],list) and isinstance(geometry['polygons'],list)
    assert geometry['vertex_overflow'] is False and geometry['polygon_overflow'] is False


def test_geometry_rejection_preserves_ram_for_visible_primitives(tmp_path,hardware_project):
    _,root,_=hardware_project
    source=Path(__file__).parent/'fixtures/nds_geometry.cpp'
    libraries=list((root/'build').rglob('libds_runtime.a'))+list((root/'build').rglob('ds_runtime.lib'))
    assert len(libraries)==1
    quote=lambda path:json.dumps(path.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(GeometryChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        'find_package(Threads REQUIRED)\n'
        f'add_executable(geometry_checks {quote(source)})\n'
        f'target_include_directories(geometry_checks PRIVATE {quote(root/"native/dsr/runtime/include")})\n'
        f'target_link_libraries(geometry_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n  target_link_libraries(geometry_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode==0,run.stdout+run.stderr
    exe=next(p for p in (build/'geometry_checks',build/'geometry_checks.exe',
        build/'Release/geometry_checks.exe') if p.exists())
    run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr


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


def test_exported_host_exclusively_owns_save_until_process_exit(tmp_path,hardware_project):
    _,root,exe=hardware_project
    save=tmp_path/'shared.sav'
    process=subprocess.Popen([str(exe),'--assets',str(root/'assets'),'--save',str(save),
        '--headless','--frames','1000000'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+10
        while not save.exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert save.exists() and process.poll() is None, 'first host did not commit a save while holding its lease'
        before=save.read_bytes()
        # The first flush replaces the save inode atomically. Its stable sidecar
        # must still exclude the next process, including path aliases.
        for alias in (save,tmp_path/'..'/tmp_path.name/'shared.sav'):
            assert 'Cannot lock cartridge save' in execute(exe,root,'--save',alias,ok=False)
            assert save.read_bytes()==before
        execute(exe,root,'--save',tmp_path/'independent.sav')
        assert save.read_bytes()==before
        if os.name!='nt':
            linked=tmp_path/'linked-folder';linked.symlink_to(tmp_path,target_is_directory=True)
            assert 'Cannot lock cartridge save' in execute(exe,root,'--save',linked/save.name,ok=False)
            assert save.read_bytes()==before
    finally:
        process.terminate()
        process.wait(timeout=10)
    # Abrupt process death releases OS ownership despite the persistent
    # sidecar. A normal exit must release it too.
    execute(exe,root,'--save',save)
    execute(exe,root,'--save',save)


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
        f'add_executable(register_checks {quoted(Path(__file__).parent/"fixtures/nds_registers.cpp")})\n'
        f'target_include_directories(register_checks PRIVATE {quoted(runtime/"include")})\n'
        f'target_link_libraries(register_checks PRIVATE {quoted(library)} Threads::Threads)\n'
        f'target_include_directories(runtime_checks PRIVATE {quoted(runtime/"include")} {quoted(runtime/"core/include")} {quoted(runtime/"core/src")})\n'
        f'target_link_libraries(runtime_checks PRIVATE {quoted(library)} Threads::Threads)\n'
        'if(WIN32)\n target_compile_definitions(runtime_checks PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)\n'
        ' target_link_libraries(runtime_checks PRIVATE bcrypt)\n'
        ' target_compile_definitions(register_checks PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)\n'
        ' target_link_libraries(register_checks PRIVATE bcrypt)\nendif()\n')
    for cmd in (['cmake','-S',str(tmp_path),'-B',str(tmp_path/'build')],
                ['cmake','--build',str(tmp_path/'build'),'--config','Release','--parallel','2']):
        done=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in (tmp_path/'build/runtime_checks',tmp_path/'build/runtime_checks.exe',
                        tmp_path/'build/Release/runtime_checks.exe') if p.is_file())
    done=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
    assert done.returncode==0,done.stdout+done.stderr
    register_exe=exe.with_name(exe.name.replace('runtime_checks','register_checks'))
    done=subprocess.run([str(register_exe)],capture_output=True,text=True,timeout=30)
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


@pytest.mark.parametrize('local',[False,True])
def test_instrumented_shared_return_preserves_caller_with_return_checks(tmp_path,sdk,local):
    def make():
        raw,profile=hardware()
        if not local:
            symbols=json.loads((Path(__file__).parent/'fixtures/nds-hardware/program.json').read_text())['arm9']['symbols']
            entry=next(item for item in profile['code']['arm9'] if item['address']==symbols['traced_start'])
            entry['size']=symbols['traced_exit']-symbols['traced_start']
            profile['code']['arm9'].append(dict(address=symbols['traced_exit'],
                size=symbols['traced_exit_end']-symbols['traced_exit'],mode='thumb'))
        return raw,profile
    _,root,exe=generate(tmp_path/'instrumented',make,cmake_options=('-DCMAKE_CXX_FLAGS=-DDSR_RET_CHECK',))
    result=execute(exe,root,'--save',tmp_path/'game.sav')
    assert result['observed'][17:]==[42,90,0,0,7,4]
    assert result['observed'][14]==63  # ordinary nested BL still resumes its caller


@pytest.mark.parametrize('entry_probe',[False,True])
def test_unbalanced_instrumentation_does_not_hide_unsupported_code(tmp_path,sdk,entry_probe):
    raw,profile=hardware();raw=bytearray(raw)
    symbols=json.loads((Path(__file__).parent/'fixtures/nds-hardware/program.json').read_text())['arm9']['symbols']
    offset,_,base,_=struct.unpack_from('<4I',raw,0x20)
    begin=offset+symbols['traced_start' if entry_probe else 'traced_exit']-base
    end=offset+symbols['traced_end']-base
    at=raw.index(struct.pack('<H',0xb002),begin,end)  # ADD sp,#8 -> #4 leaves a saved word behind
    struct.pack_into('<H',raw,at,0xb001)
    profile['input_sha256']=hashlib.sha256(raw).hexdigest()
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
