"""Render original DS geometry with OpenGL; no ROM or gameplay input is used."""
import os
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from .test_nds_native import generate, sdk  # noqa: F401
from .fixtures.nds_native import video


@pytest.fixture(scope='module')
def video_project(tmp_path_factory,sdk):
    if os.environ.get('DECOMP_REQUIRE_DS_GPU')!='1':
        pytest.skip('OpenGL execution is required in the Linux native workflow')
    return generate(tmp_path_factory.mktemp('gpu-project')/'fixture',video)


def test_generated_opengl_renderer_extends_geometry_and_preserves_ui(tmp_path,video_project):
    _,root,headless=video_project
    source=Path(__file__).parent/'fixtures/nds_video.cpp'
    shutil.copyfile(source,root/'tests/video_checks.cpp')
    with (root/'CMakeLists.txt').open('a') as file:
        file.write('''
if(NDS_WITH_SDL)
  add_executable(video_checks tests/video_checks.cpp native/video.cpp)
  target_include_directories(video_checks PRIVATE native ${DSR_ROOT}/runtime/gpu3d/src)
  target_compile_definitions(video_checks PRIVATE SDL_MAIN_HANDLED)
  target_link_libraries(video_checks PRIVATE ds_runtime SDL2::SDL2-static)
endif()
''')
    build=root/'build-video'
    configure=['cmake','-S',str(root),'-B',str(build),'-DNDS_WITH_SDL=ON','-DCMAKE_BUILD_TYPE=Release']
    if source_dir:=os.environ.get('DECOMP_DS_SDL_SOURCE'):
        configure.append('-DFETCHCONTENT_SOURCE_DIR_SDL2='+source_dir)
    for cmd in (configure,['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in (build/'video_checks',build/'video_checks.exe',build/'Release/video_checks.exe') if p.is_file())
    command=[str(exe)]
    # SDL's EGL offscreen driver works without a desktop when available. CI's
    # Xvfb route also exercises a normal window-system GL context through Mesa.
    env={**os.environ,'SDL_AUDIODRIVER':'dummy'}
    if shutil.which('xvfb-run') and os.name!='nt':command=['xvfb-run','-a',*command]
    else:env['SDL_VIDEODRIVER']='offscreen'
    done=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=60)
    assert done.returncode==0,done.stdout+done.stderr
    assert 'GPU geometry, unified camera' in done.stdout
    for name in ('unified','dual'):
        data=(tmp_path/(name+'.ppm')).read_bytes()
        assert data.startswith(b'P6\n960 540\n255\n') and len(data)==len(b'P6\n960 540\n255\n')+960*540*3
    # Exercise the entire generated guest -> session render-boundary capture ->
    # GPU presentation path, and prove presentation leaves DS execution intact.
    host=next(p for p in (build/'ds_pc',build/'ds_pc.exe',build/'Release/ds_pc.exe') if p.is_file())
    original=subprocess.run([str(headless),'--headless','--frames','8','--assets',str(root/'assets'),
        '--save',str(tmp_path/'headless.sav')],capture_output=True,text=True,timeout=30)
    assert original.returncode==0,original.stdout+original.stderr
    run=[str(host),'--frames','8','--renderer','opengl','--screen-mode','unified','--resolution','960x540',
        '--assets',str(root/'assets'),'--save',str(tmp_path/'gpu.sav'),'--capture',str(tmp_path/'guest')]
    if shutil.which('xvfb-run') and os.name!='nt':run=['xvfb-run','-a',*run]
    done=subprocess.run(run,env=env,capture_output=True,text=True,timeout=30)
    assert done.returncode==0,done.stdout+done.stderr
    reference,result=json.loads(original.stdout),json.loads(done.stdout)
    assert result['video']['renderer']=='opengl' and result['video']['unified'] and result['video']['polygons_drawn']>0
    assert result['video']['width']==960 and result['video']['height']==540
    assert all(result[key]==reference[key] for key in ('frames','ticks','top_hash','bottom_hash','cpu_pc','unimplemented_io'))
    assert (tmp_path/'guest/display.ppm').read_bytes().startswith(b'P6\n960 540\n255\n')
