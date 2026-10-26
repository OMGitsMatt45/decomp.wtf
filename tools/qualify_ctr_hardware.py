"""Qualify original 3DS Vulkan scenes and desktop layouts on the selected GPU."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from decompnet import pc
from decompnet.ctr_native import export_game
from tools.ctr_fixture import fixture
from tools.ps2_hardware import selected_device,vulkan_devices


def run(args,root,name,*,timeout=1800):
    log=root/(name+'.log')
    print(name+': '+str(log),flush=True)
    try:
        result=subprocess.run(list(map(str,args)),cwd=root,capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired as error:
        log.write_text('Validation timed out.\n',encoding='utf-8')
        raise ValueError('command timed out; inspect '+str(log)) from error
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise ValueError('command failed; inspect '+str(log))
    return result.stdout


def verify(scenes,players,inventory):
    if (scenes.get('schema')!='decomp.wtf.3ds-gpu-scenes/v1' or scenes.get('passed') is not True
        or scenes.get('renderer')!='vulkan' or scenes.get('scenes')!=4
        or scenes.get('resized_scales')!=[1,2,3,1] or scenes.get('framebuffer_preserved') is not True):
        raise ValueError('original Vulkan geometry/resize checks are incomplete')
    selected={'scenes':selected_device(inventory,dict(gpu_device=scenes.get('device')))}
    for name,screen in [('stacked','stacked')]:
        player=players.get(name,{})
        window=player.get('window') or {}
        if (player.get('schema')!='decomp.wtf.3ds-runtime-run/v1' or player.get('gpu_rendering') is not True
            or player.get('stop')!='window-frame-limit' or player.get('interpreted_instructions')!=0
            or player.get('rejected_instructions')!=0 or player.get('native_instructions',0)<=0
            or player.get('static_misses')!=[] or player.get('unimplemented_svcs')!=[]
            or player.get('unimplemented_services')!=[] or window.get('presented_frames')!=2
            or window.get('screens')!=screen
            or len(window.get('drawable',[]))!=2 or min(window['drawable'])<=0):
            raise ValueError('original native Vulkan window failed: '+name)
        selected[name]=selected_device(inventory,dict(gpu_device=window.get('device')))
    return selected


def assess(destination,*,allow_software=False,cargo_target=None):
    out=Path(destination).resolve()
    if out.exists():raise ValueError('choose a new assessment directory; existing work is preserved')
    out.mkdir(parents=True)
    report=dict(schema='decomp.wtf.3ds-hardware-assessment/v1',host=platform.platform(),
        hardware_qualified=False,original_fixture_passed=False,retail=False,manual_gameplay=False,
        physical_audio_qualified=False,physical_controller_qualified=False)
    try:
        report['vulkan_devices']=vulkan_devices()
        if not allow_software and not any(d['device_type'] in (1,2) for d in report['vulkan_devices']):
            raise ValueError('no integrated/discrete Vulkan GPU is available; software devices cannot qualify physical hardware')
        cmake=shutil.which('cmake')
        if not cmake:raise ValueError('CMake is required; use tools/qualify-3ds-hardware.ps1 to discover the Visual Studio component, or https://cmake.org/download/')
        image=out/'original loop.cxi';image.write_bytes(fixture('loop'))
        project=out/'Original 3DS source';build=project/'build'
        print('Preparing original source; Rust compilation can take several minutes.',flush=True)
        exported=export_game(image,project)
        report['backend_revision']=exported['manifest']['backend']['revision']
        report['source_integrity_verified']=pc.verify(project)['integrity_verified']
        target=Path(cargo_target).resolve() if cargo_target else build/'host'
        run([cmake,'-S',project,'-B',build,'-DCTR_DESKTOP=ON',f'-DCTR_CARGO_TARGET={target}'],out,'configure')
        run([cmake,'--build',build,'--config','Release','--parallel','2'],out,'build')
        suffix='.exe' if os.name=='nt' else ''
        binaries=target/'debug'
        scenes=json.loads(run([binaries/('ctr_gpu_scenes'+suffix)],out,'gpu-scenes',timeout=90))
        players={}
        for name,options in [('stacked',[])]:
            players[name]=json.loads(run([binaries/('ctr_runtime'+suffix),image,'--window','--window-frames','2',
                '--mute','--data',out/'original user',*options],out,'player-'+name,timeout=90))
        report['scenes']=scenes;report['players']=players
        report['selected_devices']=verify(scenes,players,report['vulkan_devices'])
        report['original_fixture_passed']=True
        report['hardware_qualified']=all(d['physical'] for d in report['selected_devices'].values())
        report['device_evidence']='Actual undecorated Vulkan device names from geometry and the two-screen window run must match integrated/discrete inventory entries.'
        if not report['hardware_qualified'] and not allow_software:
            raise ValueError('rendering passed, but the selected devices are software, virtual or unverified; inspect hardware-assessment.json')
        return report
    except KeyboardInterrupt:
        report['interrupted']=True;report['error']='Validation interrupted before completion.'
        raise
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        (out/'hardware-assessment.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--allow-software',action='store_true',help='development comparison; never qualifies software as physical')
    parser.add_argument('--cargo-target',type=Path,help='optional reusable compiler cache for development')
    args=parser.parse_args()
    try:print(json.dumps(assess(args.destination,allow_software=args.allow_software,cargo_target=args.cargo_target),indent=2))
    except KeyboardInterrupt:parser.exit(130,'Validation interrupted. Results: '+str(args.destination/'hardware-assessment.json')+'\n')
    except Exception as error:parser.exit(1,str(error)+'\nResults: '+str(args.destination/'hardware-assessment.json')+'\n')
