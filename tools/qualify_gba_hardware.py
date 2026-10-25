"""Build an original standalone GBA project and assess the selected OpenGL GPU."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from decompnet import pc
from decompnet.gba_native import _cmake, export_game
from tests.fixtures.gba_native import hardware
from tools.ps2_hardware import selected_device, vulkan_devices


def run(command, cwd, log, *, env=None, timeout=1800):
    print(f'{log.stem}: running {Path(str(command[0])).name}; logs: {log}', flush=True)
    try:
        result=subprocess.run(list(map(str,command)),cwd=cwd,env=env,capture_output=True,
            text=True,encoding='utf-8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode('utf-8','replace') if isinstance(value,bytes) else (value or '')
        log.write_text(decoded(error.stdout)+decoded(error.stderr)+'\nTimed out.\n',encoding='utf-8')
        raise ValueError('command timed out; inspect '+str(log)) from error
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:
        raise ValueError('command failed; inspect '+str(log))
    return result.stdout


def executable(build, name):
    for path in (build/name,build/(name+'.exe'),build/'Release'/(name+'.exe')):
        if path.is_file():
            return path
    raise ValueError('build did not produce '+name+' under '+str(build))


def picture(path):
    with Path(path).open('rb') as stream:
        if stream.readline()!=b'P6\n':
            raise ValueError('capture is not RGB PPM')
        width,height=map(int,stream.readline().split())
        if stream.readline()!=b'255\n':
            raise ValueError('unsupported capture precision')
        pixels=stream.read()
    if width<=0 or height<=0 or len(pixels)!=width*height*3:
        raise ValueError('capture dimensions differ')
    return width,height,pixels


def verify_player(report, capture):
    if (not report.get('gpu_rendering') or report.get('renderer')!='opengl' or
        report.get('interpreted_cycles')!=0 or report.get('misses') or report.get('frames')!=120):
        raise ValueError('standalone player did not complete strict native OpenGL execution')
    width,height,pixels=picture(capture)
    if report.get('drawable')!=[width,height]:
        raise ValueError('player drawable and GPU capture dimensions differ')
    # The original cartridge renders red. Verify the full GPU capture including
    # letterboxing at the actual DPI-scaled drawable, rather than logical size.
    w=width;h=w*2//3
    if h>height:
        h=height;w=h*3//2
    left=(width-w)//2;top=height-(height-h)//2-h
    for y in range(height):
        row=(b'\0\0\0'*left+b'\xff\0\0'*w+b'\0\0\0'*(width-left-w)
            if top<=y<top+h else b'\0\0\0'*width)
        if pixels[y*width*3:(y+1)*width*3]!=row:
            raise ValueError('standalone GPU picture differs from original cartridge at row '+str(y))


def assess(destination, *, allow_software=False):
    out=Path(destination).resolve()
    if out.exists():
        raise ValueError('choose a new assessment directory; existing work is preserved')
    out.mkdir(parents=True)
    report=dict(schema='decomp.wtf.gba-hardware-assessment/v1',host=platform.platform(),
        hardware_qualified=False,original_fixture_passed=False,retail=False,
        manual_gameplay=False,physical_audio_qualified=False,physical_controller_qualified=False)
    try:
        # Inventory supplies a typed hardware identity, not the GBA renderer.
        # The actual OpenGL device name must match an integrated/discrete entry.
        try:
            report['vulkan_devices']=vulkan_devices()
        except Exception as error:
            report['vulkan_devices']=[]
            report['inventory_error']=str(error)
        data,profile=hardware()
        rom=out/'original.gba';rom.write_bytes(data)
        mapping=out/'profile.json';mapping.write_text(json.dumps(profile),encoding='utf-8')
        root=out/'PC game';build=root/'build'
        print('Preparing the original GBA export; source verification and compilation can take several minutes.',flush=True)
        exported=export_game(rom,root,profile=mapping,save_type='sram',log=lambda text:print(text,flush=True))
        report['backend_revision']=exported['manifest']['backend']['revision']
        report['source_integrity_verified']=pc.verify(root)['integrity_verified']
        cmake=_cmake()
        run([sys.executable,'-I',root/'tools/extract_assets.py',rom],out,out/'extract.log')
        configure=[cmake,'-S',root,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DGBA_BUILD_GPU_TESTS=ON']
        if os.environ.get('GBA_SDL3_DIR'):
            configure.append('-DSDL3_DIR='+os.environ['GBA_SDL3_DIR'])
        run(configure,out,out/'configure.log')
        run([cmake,'--build',build,'--config','Release','--parallel','2'],out,out/'build.log')
        env={**os.environ,'SDL_AUDIODRIVER':'dummy'}
        scene_report=out/'gpu-scenes.json'
        run([executable(build,'gba_gpu_tests'),'--report',scene_report],out,out/'gpu-scenes.log',env=env,timeout=90)
        scenes=json.loads(scene_report.read_text(encoding='utf-8'))
        if (scenes.get('schema')!='decomp.wtf.gba-gpu-scenes/v1' or not scenes.get('passed') or
            scenes.get('scenes')!=18 or scenes.get('renderer')!='opengl' or not scenes.get('resize_passed')):
            raise ValueError('GPU scene qualification is incomplete')
        report['scenes']=scenes
        capture=out/'gpu-picture.ppm'
        player=json.loads(run([executable(build,'gba_pc'),'--renderer','opengl','--frames','120',
            '--strict-static','--keys','1','--resize','60:480x320','--display-capture',capture,
            '--save',out/'original.sav'],out,out/'player.log',env=env,timeout=90))
        verify_player(player,capture)
        report['player']=player
        report['original_fixture_passed']=True
        report['selected_devices']={name:selected_device(report['vulkan_devices'],dict(gpu_device=device))
            for name,device in [('scenes',scenes.get('device')),('player',player.get('device'))]}
        report['hardware_qualified']=all(d['physical'] for d in report['selected_devices'].values())
        report['device_evidence']='Physical qualification requires actual OpenGL renderer names to match integrated/discrete Vulkan inventory exactly. Rendering uses OpenGL.'
        if not report['hardware_qualified'] and not allow_software:
            raise ValueError('graphics checks passed, but the selected OpenGL renderer could not be verified as physical; inspect the device names and inventory in hardware-assessment.json')
        return report
    except KeyboardInterrupt:
        report['interrupted']=True
        report['error']='Validation was interrupted before completion.'
        raise
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        (out/'hardware-assessment.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--allow-software',action='store_true',help='developer comparison; never qualifies software rendering as physical hardware')
    args=parser.parse_args()
    try:
        print(json.dumps(assess(args.destination,allow_software=args.allow_software),indent=2))
    except KeyboardInterrupt:
        parser.exit(130,'Validation interrupted. Results: '+str(args.destination/'hardware-assessment.json')+'\nRetry with a new output folder and allow the build to finish.\n')
    except Exception as error:
        parser.exit(1,str(error)+'\nResults: '+str(args.destination/'hardware-assessment.json')+'\n')
