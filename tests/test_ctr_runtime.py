"""Execute an original ARM11 program against its independent bundled runtime."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from decompnet import pc
from decompnet.ctr_native import export_runtime, runtime_provider, media
from tools.ctr_fixture import fixture,cro,with_romfs


def command(args, *, timeout=900, env=None):
    result = subprocess.run(list(map(str,args)),capture_output=True,text=True,
                            encoding='utf-8',errors='replace',timeout=timeout,env=env)
    assert result.returncode==0,(result.stdout+result.stderr)[-12000:]
    return result


@pytest.fixture(scope='module')
def original_runtime(tmp_path_factory):
    if os.environ.get('DECOMP_TEST_3DS_RUNTIME')!='1':
        pytest.skip('set DECOMP_TEST_3DS_RUNTIME=1 for the source-shipped Rust/Vulkan core build')
    assert shutil.which('cmake') and shutil.which('cargo'), 'runtime build requires CMake, Rust 1.95+ and C/C++'
    root=tmp_path_factory.mktemp('original 3DS runtime')
    image=root/'original.cxi'
    image.write_bytes(with_romfs(fixture('services'),[('OriginalARM.cro',cro('OriginalARM')),
        ('OriginalThumb.cro',cro('OriginalThumb',thumb=True)),('Alias.cro',cro('OriginalARM')),
        ('OriginalSave.cro',cro('OriginalSave',save=True))]))
    project=root/'Independent source'
    stream=SimpleNamespace(stat=image.stat,open=image.open)
    exported=export_runtime('streamed-original.cxi',project,screen_mode='unified',source=stream)
    assert exported['integrity_verified'] and not exported['presentation_declared']
    manifest=exported['manifest']
    assert manifest['qualification']['retail'] is False
    assert manifest['development_presentation']['screen_mode']=='unified'
    assert len(json.loads((project/'analysis.json').read_text())['modules'])==4
    assert manifest['fallback']==dict(interpreter=True,runtime_compilation=False,default='strict')
    assert (project/'native/runtime/LICENSE').is_file()
    assert (project/'native/app/Cargo.lock').is_file()
    assert not list((project/'native').rglob('.git'))
    pins=json.loads((project/'runtime-sources.json').read_text())
    assert pins['runtime_commit']==runtime_provider.COMMIT
    # Reuse only the owner's selected compiler cache, never another game source.
    target=Path(os.environ.get('DECOMP_3DS_TEST_CARGO_TARGET',project/'build/host')).resolve()
    command(['cmake','-S',project,'-B',project/'build',f'-DCTR_CARGO_TARGET={target}','-DCTR_DESKTOP=ON'])
    def build():
        command(['cmake','--build',project/'build','--config','Release','--parallel','2'])
    build()
    suffix='.exe' if os.name=='nt' else ''
    binary=target/'debug'/('ctr_runtime'+suffix)
    scenes=target/'debug'/('ctr_gpu_scenes'+suffix)
    assert binary.is_file() and scenes.is_file()
    host_env=os.environ.copy()
    if os.environ.get('DECOMP_TEST_3DS_AUDIO_NULL')=='1':
        # ALSA treats spaces as separators in its configuration-path list.
        # Keep the independent project's paths spaced, but use a separate
        # ordinary path for the virtual output device's configuration.
        config=tmp_path_factory.mktemp('ctr-audio')/'null.conf'
        config.write_text('pcm.!default { type null }\n')
        host_env['ALSA_CONFIG_PATH']=str(config)
    def run(*args, status=0):
        result=subprocess.run([str(binary),str(image),'--data',str(root/'user'),*args],
                              capture_output=True,text=True,timeout=90,env=host_env)
        assert result.returncode==status,result.stdout+result.stderr
        return json.loads(result.stdout)
    return project,image,binary,scenes,build,run


def test_services_scheduler_identity_and_both_interpreter_guards(original_runtime):
    project,image,binary,_scenes,build,run=original_runtime
    report=run('--cycles','1000000')
    assert report['process_exited'] and report['r0']==31
    assert report['native_instructions']==168 and report['interpreted_instructions']==0
    assert report['static_misses']==[] and report['rejected_instructions']==0
    assert report['unimplemented_svcs']==[] and report['unimplemented_services']==[]
    assert {'cfg:u','fs:USER'}<=set(report['services'])
    assert report['cycles']>240000  # Actual asynchronous ExeFS read, not a stubbed reply.
    report=run('--cycles','1',status=2)
    assert report['cycles']==1 and report['native_instructions']==1
    assert report['interpreted_instructions']==0 and report['static_misses']==[]

    # Bind the original at launch, even when the copied project is standalone.
    raw=image.read_bytes();image.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    failed=subprocess.run([str(binary),str(image)],capture_output=True,text=True,timeout=15)
    assert failed.returncode==1 and 'SHA-256 differs' in failed.stderr
    image.write_bytes(raw)

    source=project/'game/code000.c';text=source.read_text()
    pattern=r'(/\* 00100000 E3A08000 \*/\n)(.*?)(?=L_00100004:)'
    found=re.search(pattern,text,re.S);assert found
    body=found.group(2)
    try:
        # Editing generated C affects the linked result without patching the ROM.
        assert '0x00000000u' in body
        source.write_text(text[:found.start(2)]+body.replace('0x00000000u','0x80000000u')+text[found.end(2):])
        build();assert run('--cycles','1000000')['r0']==0x8000001f

        # The inline interpreter path must reject before executing any instruction.
        source.write_text(text[:found.start(2)]+'    INTERPRET(0x00100000u, 0xe3a08000u);\n'+text[found.end(2):])
        build();report=run('--cycles','1000000',status=1)
        assert report['stop']=='fault' and report['rejected_instructions']==1
        assert report['interpreted_instructions']==0 and report['static_misses']==[0x100000]
        report=run('--cycles','1000000','--allow-interpreter')
        assert report['r0']==31 and report['interpreted_instructions']==1
        assert report['native_instructions']==167 and report['rejected_instructions']==0

        # A missing dispatch target is independently guarded as well.
        source.write_text(text[:found.start(2)]+'    ctx->r[15]=0; return;\n'+text[found.end(2):])
        build();report=run('--cycles','1000000',status=1)
        assert report['stop']=='fault' and report['static_misses']==[0]
        assert report['interpreted_instructions']==0

        # Neither an unimplemented SVC nor unknown IPC may silently succeed.
        assert text.count('SVC(0x0010001Cu, 0x1u)')==1
        source.write_text(text.replace('SVC(0x0010001Cu, 0x1u)','SVC(0x0010001Cu, 0x7fu)'))
        build();report=run('--cycles','1000000',status=1)
        assert report['stop']=='unimplemented-service' and report['unimplemented_svcs']==[0x7f]
        assert report['interpreted_instructions']==0
        assert text.count('0x00050000u')==1
        source.write_text(text.replace('0x00050000u','0x7fff0000u'))
        build();report=run('--cycles','1000000',status=1)
        assert report['stop']=='unimplemented-service' and report['unimplemented_services']
        assert report['interpreted_instructions']==0
    finally:
        source.write_text(text)
        build()


def test_adaptive_layout_touch_and_vulkan_scenes(original_runtime):
    _project,_image,_binary,scenes,_build,_run=original_runtime
    command([scenes,'--layout-only'],timeout=60)
    if os.environ.get('DECOMP_TEST_3DS_GPU')=='1':
        report=json.loads(command([scenes],timeout=90).stdout)
        assert report['passed'] and report['scenes']==4
        assert report['resized_scales']==[1,2,3,1] and report['framebuffer_preserved']
        assert not report['physical_device_qualified']


def test_translated_arm_and_thumb_modules_move_reload_and_unload(original_runtime):
    project,image,binary,_scenes,_build,_run=original_runtime
    probe=binary.with_name('ctr_module_scenes'+('.exe' if os.name=='nt' else ''))
    rows=json.loads((project/'analysis.json').read_text())['modules']
    for row in rows:
        path=project/'assets/modules'/row['file'];raw=path.read_bytes()
        name_offset=int.from_bytes(raw[0xc0:0xc4],'little')
        module=raw[name_offset:].split(b'\0')[0].decode('ascii')
        if module=='OriginalSave':continue
        report=json.loads(command([probe,image,path,module],timeout=30).stdout)
        assert report['passed'] and report['native_instructions']==4
        assert report['interpreted_instructions']==0 and report['provenance_checked']


def test_native_savedata_survives_relaunch_and_preserves_other_files(original_runtime,tmp_path):
    project,image,binary,_scenes,_build,_run=original_runtime
    probe=binary.with_name('ctr_module_scenes'+('.exe' if os.name=='nt' else ''))
    row=next(row for row in json.loads((project/'analysis.json').read_text())['modules']
             if row['path']=='OriginalSave.cro')
    module=project/'assets/modules'/row['file']
    user=tmp_path/'independent user data'
    saved=user/'user/savedata'/'000400000FF3DE00'
    for expected in (1,2):
        report=json.loads(command([probe,'--save',image,module,user],timeout=30).stdout)
        assert report['passed'] and report['counter']==expected
        assert report['native_instructions']>100 and report['interpreted_instructions']==0
        assert (saved/'counter.bin').read_bytes()==expected.to_bytes(4,'little')
        if expected==1:(saved/'preserve.txt').write_text('owner save data')
    assert (saved/'preserve.txt').read_text()=='owner save data'
    # Corrupt counters fail without formatting the existing archive.
    (saved/'counter.bin').write_bytes(b'\xff'*4)
    failed=subprocess.run([str(probe),'--save',str(image),str(module),str(user)],
                          capture_output=True,text=True,timeout=30)
    assert failed.returncode!=0 and 'save fixture' in failed.stderr
    assert (saved/'counter.bin').read_bytes()==b'\xff'*4
    assert (saved/'preserve.txt').read_text()=='owner save data'


def test_compressed_executable_bytes_agree_with_independent_runtime_loader(original_runtime):
    project,_image,binary,_scenes,_build,_run=original_runtime
    image=project.parent/'original-compressed.cxi';image.write_bytes(fixture('blz-arm'))
    expected=project.parent/'original-decoded.bin';expected.write_bytes(media.load(image,include_code=True)['code'])
    probe=binary.with_name('ctr_module_scenes'+('.exe' if os.name=='nt' else ''))
    report=json.loads(command([probe,'--loaded-code',image,expected],timeout=30).stdout)
    assert report['passed'] and report['interpreted_instructions']==0


def test_audio_resampling_queue_and_controller_input_merge(original_runtime):
    project,_image,_binary,_scenes,_build,_run=original_runtime
    env=os.environ.copy()
    if os.environ.get('DECOMP_TEST_3DS_AUDIO_NULL')=='1':
        env['ALSA_CONFIG_PATH']=str(next(project.parent.parent.glob('ctr-audio*/null.conf')))
    result=command(['cmake','--build',project/'build','--target','ctr_runtime_tests','--config','Release'],timeout=180,env=env)
    assert '0 failed' in result.stdout and 'gamepad::tests::' in result.stdout
    assert 'audio::tests::' in result.stdout


def test_vulkan_window_with_both_screen_arrangements(original_runtime):
    if os.environ.get('DECOMP_TEST_3DS_WINDOW')!='1':
        # Runtime CI on Windows still builds the desktop source. A runner
        # without a display/device must not be presented as a window pass.
        return
    project,_image,_binary,_scenes,build,run=original_runtime
    source=project/'game/code000.c';text=source.read_text()
    # Keep an original title alive through presentation; no game data is used.
    loop=re.sub(r'(/\* 00100000 E3A08000 \*/\n).*?(?=L_00100004:)',
        r'\1    goto L_00100000;\n',text,flags=re.S)
    assert loop!=text
    try:
        source.write_text(loop);build()
        for options in (['--screens','stacked'],[],['--primary','bottom']):
            report=run('--window','--window-frames','2',*options)
            assert report['window']['presented_frames']==2 and report['gpu_rendering']
            assert report['interpreted_instructions']==0 and not report['retail_qualified']
            assert not report['window']['physical_audio_qualified']
            if os.environ.get('DECOMP_TEST_3DS_AUDIO_NULL')=='1':
                # This original CPU loop never starts the DSP; it is silent.
                # A separate tone test checks nonzero audio through the callback.
                assert report['window']['audio_output_open'],report['window']
    finally:
        source.write_text(text);build()
