"""Build/run an actual standalone PS2 export from an original CC0 EE program."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import re

from decompnet import pc,ps2_native
from decompnet.ps2_native import provider
from decompnet.ps2_native.extract_assets import stage
from tests.fixtures.ps2_port import stripped_original
from tools.qualify_ps2_runtime import executable

ROOT=Path(__file__).resolve().parents[1]


def run(command,cwd,log,*,env=None,timeout=1800,success=True):
    print(f'{log.stem}: running {Path(str(command[0])).name}; logs will be saved to {log}',flush=True)
    try:
        result=subprocess.run(list(map(str,command)),cwd=cwd,env=env,capture_output=True,text=True,
            encoding='utf-8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def decoded(value):return value.decode('utf-8','replace') if isinstance(value,bytes) else (value or '')
        log.write_text(decoded(error.stdout)+decoded(error.stderr)+'\nCommand timed out.\n',encoding='utf-8')
        raise ValueError('command timed out; inspect '+str(log)) from error
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if (result.returncode==0)!=success:raise ValueError('unexpected command result; inspect '+str(log))
    return result


def qualify_static_execution(project,build,reference_build,out):
    original=project/'tests/iop/original.irx'
    native=run([executable(build,'ps2_iop_probe'),original],out,out/'native-iop.log',timeout=30)
    reference=run([executable(reference_build,'ps2_iop_probe'),original],out,out/'reference-iop.log',timeout=30)
    if native.stdout!=reference.stdout:raise ValueError('native IOP contexts differ from the reference')
    count=0
    for program in range(4):
        for unit in (0,1):
            for seed in range(4):
                for budget in (3,4096):
                    outputs=[];case=f'{program}-{unit}-{seed}-{budget}'
                    for role,folder in (('native',build),('reference',reference_build)):
                        result=out/f'vu-{role}-{case}.bin';outputs.append(result)
                        run([executable(folder,'ps2_vu_probe'),unit,seed,budget,
                             project/f'tests/vu/program{program}.bin',result,'original'],
                            out,out/f'vu-{role}-{case}.log',timeout=30)
                    if outputs[0].read_bytes()!=outputs[1].read_bytes():
                        raise ValueError('native vector state differs from the reference: '+case)
                    count+=1
    for unit in (0,1):
        run([executable(build,'ps2_vu_probe'),unit,0,4096,project/'tests/vu/program0.bin',
             out/f'vu-changed-{unit}.bin','changed'],out,out/f'vu-changed-{unit}.log',timeout=30)
    if os.name!='nt':
        symbols=run(['nm','-C',executable(build,'ps2_pc')],out,out/'native-player-symbols.log',timeout=30).stdout
        for forbidden in ('VU1Interpreter::execUpper(unsigned int)','VU1Interpreter::execLower(unsigned int',
                          'ps2_vu_program::Run::exactUpper(unsigned int)'):
            if forbidden in symbols:raise ValueError('dynamic vector instruction engine is linked: '+forbidden)
    return dict(vector_cases=count,changed_pair_rejections=2,iop_contexts_match=True,
                native_iop_changed_code_rejected=True,instruction_engine_fallback=False)


def picture(path):
    with path.open('rb') as stream:
        if stream.readline()!=b'P6\n':raise ValueError('capture is not RGB PPM')
        w,h=map(int,stream.readline().split())
        if stream.readline()!=b'255\n':raise ValueError('unsupported capture precision')
        pixels=stream.read()
    if len(pixels)!=w*h*3:raise ValueError('capture size differs')
    def pixel(x,y):return tuple(pixels[(y*w+x)*3:(y*w+x)*3+3])
    if pixel(w*3//8,h*3//8)!=(255,0,0) or pixel(w-1,h-1)!=(0,0,0):
        raise ValueError('native frame differs from the original triangle geometry')
    return dict(width=w,height=h,red_pixels=sum(pixels[n:n+3]==b'\xff\0\0' for n in range(0,len(pixels),3)))


def qualify(destination,*,sdk=None,execute=True):
    out=Path(destination).resolve()
    if out.exists():raise ValueError('choose a new assessment directory; existing work is preserved')
    out.mkdir(parents=True)
    sdk=Path(sdk).resolve() if sdk else out/'Pinned source runtime'
    progress=lambda message:print(message,flush=True)
    if not sdk.exists():provider.download(sdk,log=progress)
    pins=provider.verify(sdk,log=progress);os.environ['DECOMP_PS2_PORT_SDK']=str(sdk)
    owner=out/'original-gs.elf';owner.write_bytes(stripped_original())
    project=out/'Standalone PS2 source with spaces'
    exported=ps2_native.export(owner,project,title='Original PS2 graphics fixture',renderer='vulkan',log=print)
    recovered=json.loads((project/'game/profile.json').read_text(encoding='utf-8'))
    if recovered['modules'][0].get('recovery',{}).get('method')!='bounded-closed-reachable-cfg':
        raise ValueError('the stripped original fixture did not use automatic recovery')
    stage(owner,project)
    # The output builds independently: no app Python package, emitter or console
    # matching toolchain participates in this CMake build.
    build=out/'Standalone build with spaces'
    extra=json.loads(os.environ.get('DECOMP_PS2_CMAKE_ARGS','[]'))
    run(['cmake','-S',project,'-B',build,'-DDECOMP_PS2_BUILD_SERVICE_TESTS=ON','-DDECOMP_PS2_BUILD_NATIVE_TESTS=ON',*extra],out,out/'configure.log')
    run(['cmake','--build',build,'--target','ps2_pc','ps2_service_probe','ps2_mpeg_probe','ps2_vu_probe','ps2_iop_probe','--config','Release','--parallel','2'],out,out/'build.log')
    reference_build=out/'Separate reference build'
    run(['cmake','-S',project,'-B',reference_build,'-DDECOMP_PS2_REFERENCE=ON',
         '-DDECOMP_PS2_BUILD_NATIVE_TESTS=ON','-DDECOMP_PS2_BUILD_RUNTIME_TESTS=ON',*extra],out,out/'reference-configure.log')
    run(['cmake','--build',reference_build,'--target','ps2_runtime_tests','ps2_vu_probe','ps2_iop_probe',
         '--config','Release','--parallel','2'],out,out/'reference-build.log')
    static_execution=qualify_static_execution(project,build,reference_build,out)
    native=executable(build,'ps2_pc')
    reports={}
    services=out/'Original service state';services.mkdir();service_results={}
    image=bytearray(6*2048);image[3*2048:3*2048+3000]=bytes(n%251 for n in range(3000))
    (services/'disc.img').write_bytes(image)
    for mode in ('write','read'):
        service=run([executable(build,'ps2_service_probe'),services,mode],out,out/f'services-{mode}.log',timeout=30)
        service_results[mode]=json.loads(service.stdout)
    movie=run([executable(build,'ps2_mpeg_probe')],out,out/'mpeg.log',timeout=30)
    service_results['mpeg']=json.loads(movie.stdout)
    suites={}
    for suite in ('pad','io','kernel','interrupt','fiber','memory','vu1','vu_upper','vu_program','vu0','gs','iop','native_iop','sif_rpc','sif_dma','media','irx'):
        result=run([executable(reference_build,'ps2_runtime_tests'),'--suite',suite],services,out/('runtime-'+suite+'.log'),
                   timeout=1200 if suite=='vu1' else 90)
        count=re.search(r'Total Tests: (\d+)\s+Passed: (\d+)\s+Failed: (\d+)',result.stdout)
        if not count or int(count[1])<1 or count[1]!=count[2] or int(count[3]):
            raise ValueError('incomplete pinned runtime test result: '+suite)
        suites[suite]=int(count[1])
    if execute:
        for renderer in ('vulkan','software'):
            report=out/(renderer+'.json');capture=out/(renderer+'.ppm')
            run([native,'--project',project,'--renderer',renderer,'--resolution','320x320',
                '--resize','10:640x480','--frames','20','--seconds','10','--report',report,'--capture',capture],
                out,out/(renderer+'.log'),timeout=30)
            data=json.loads(report.read_text())
            if (not data['success'] or data['drawable']!=[640,480] or data['source']!=[64,64] or
                data['missing_functions'] or data['execution_failures'] or data['presented_frames']<20 or
                data['iop_interpreter'] or data['vu_interpreter'] or data['iop_interpreted_instructions'] or
                data['vu_interpreted_pairs'] or data['iop_coverage_misses'] or data['vu_coverage_misses']):
                raise ValueError('standalone runtime/display result differs: '+renderer)
            expected=exported['manifest']['code_generation'][0]['guards']['original_elf_sha256']
            if data.get('resident_modules')!=[expected]:raise ValueError('original resident module bytes differ after execution')
            if renderer=='vulkan' and (not data['gpu_primitives'] or data['internal_scale']!=10 or data['scale_limited']):
                raise ValueError('adaptive Vulkan geometry rendering failed')
            reports[renderer]=dict(run=data,picture=picture(capture))
        # Deliberate owner code edits must be reported as failures, including
        # exceptions that cross the EE worker rather than the host main thread.
        asset=project/'assets/cd/boot.elf';before=asset.read_bytes()
        try:
            changed=bytearray(before);changed[0x100]^=1;asset.write_bytes(changed)
            report=out/'changed-code.json'
            run([native,'--project',project,'--renderer','software','--seconds','2','--report',report],
                out,out/'changed-code.log',timeout=15,success=False)
            data=json.loads(report.read_text())
            if data['success'] or not data['execution_failures']:raise ValueError('changed EE code was not rejected')
            reports['changed-code']=data
        finally:asset.write_bytes(before)
    env=dict(os.environ,SDL_VIDEODRIVER='dummy',VK_DRIVER_FILES=str(out/'missing-driver.json'),VK_ICD_FILENAMES=str(out/'missing-driver.json'))
    run([native,'--project',project,'--renderer','vulkan','--seconds','1','--report',out/'missing-gpu.json'],
        out,out/'missing-gpu.log',env=env,timeout=15,success=False)
    missing=json.loads((out/'missing-gpu.json').read_text())
    if missing['success'] or 'required Vulkan renderer failed' not in missing['error']:
        raise ValueError('required GPU failure was not explicit')
    # Reuse the exact emitter built by the actual export for the original VU
    # instruction->generated C++->independent arithmetic oracle checks.
    integration=exported['manifest']['backend']['revision']
    emitter_build=ps2_native.emitter_directory(sdk,integration)/'build'
    env=dict(os.environ,DECOMP_PS2_PATCHED_EMITTER=str(executable(emitter_build,'ps2_recomp')))
    run([sys.executable,'-m','pytest','-q','tests/test_ps2_native_vu.py',
         'tests/test_ps2_iop_codegen.py','tests/test_ps2_iop_native.py',
         '--basetemp',out/'Instruction checks with spaces'],
        ROOT,out/'vu.log',env=env)
    if provider.verify(sdk,log=progress)!=pins:raise ValueError('the exporter modified pinned source')
    verified=pc.verify(project)
    result=dict(schema='decomp.wtf.ps2-port-assessment/v1',source_sha256=pins['source_sha256'],
        backend_revision=integration,host_build=True,graphics_executed=execute,retail=False,
        integrity_verified=verified['integrity_verified'],runs=reports,required_gpu_failure=missing,
        native_services=service_results,runtime_suites=suites,static_execution=static_execution,
        original_input_sha256=exported['manifest']['inputs'][0]['sha256'])
    (out/'assessment.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    parser.add_argument('--sdk-root',type=Path);parser.add_argument('--build-only',action='store_true')
    args=parser.parse_args()
    print(json.dumps(qualify(args.destination,sdk=args.sdk_root,execute=not args.build_only),indent=2))
