"""Standalone PS2 native project export with explicit input-bound code maps."""
from contextvars import ContextVar
import csv
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .. import pc,toolchains
from . import codegen,media,modules,profile,provider,registry,reports,runtime_patch

BACKEND_ID='ps2-ps2recomp-experimental'
_progress=ContextVar('ps2_native_progress',default=None)
_evidence=ContextVar('ps2_native_evidence',default=None)


def _source(name):return resources.files(__package__).joinpath(name).read_text(encoding='utf-8')


def revision():
    digest=hashlib.sha256()
    base=Path(__file__).parent
    for path in sorted(base.rglob('*')):
        if path.is_file() and path.suffix in ('.py','.hpp','.cpp','.json','.cmake','.md','.gz','.txt','.manifest'):
            digest.update(path.relative_to(base).as_posix().encode()+b'\0'+path.read_bytes())
    return digest.hexdigest()


def _log(text):
    callback=_progress.get()
    if callback:callback(text)


def _run(command,cwd,what,timeout=1800):
    _log(what+'...')
    try:result=subprocess.run(list(map(str,command)),cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    except subprocess.TimeoutExpired as error:raise pc.PCError(what+' timed out') from error
    output=result.stdout+result.stderr
    evidence=_evidence.get()
    if evidence is not None and what.startswith('Translate PS2 module'):
        evidence.append((what,output))
    if result.returncode:raise pc.PCError(what+' failed:\n'+output[-5000:])
    return output


def _dependencies(output):
    dependencies=json.loads(_source('dependencies.json'))
    text='include(FetchContent)\n'+ '\n'.join('FetchContent_Declare('+d['name']+'\n  URL "'+d['url']+
        '"\n  URL_HASH SHA256='+d['archive_sha256']+'\n  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)' for d in dependencies)+'\n'
    output.write_text(text,encoding='utf-8')


def _sdk():
    override=os.environ.get('DECOMP_PS2_PORT_SDK')
    root=Path(override).resolve() if override else toolchains.root()/'ps2-native-runtime'
    if not root.exists():provider.download(root,log=_log)
    return root,provider.verify(root)


def _emitter(sdk):
    # Build outside the pinned cache. An integration revision gets a separate
    # source/build tree, so previous working installations remain reviewable.
    integration=revision()
    work=sdk.parent/'.ps2-native-builds'/integration[:16]
    source=work/'source'
    marker=work/'integration.json'
    if not source.exists():
        work.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.source-',dir=work) as tmp:
            copied=Path(tmp)/'source';shutil.copytree(sdk,copied)
            runtime_patch.patch_emitter(copied)
            expected=dict(revision=integration,source_sha256=provider.fingerprint(copied))
            copied.rename(source)
            marker.write_text(json.dumps(expected)+'\n',encoding='utf-8')
    if not marker.is_file():raise pc.PCError('PS2 emitter cache has no source identity; choose a clean toolchain cache')
    expected=json.loads(marker.read_text(encoding='utf-8'))
    if expected.get('revision')!=integration or provider.fingerprint(source)!=expected.get('source_sha256'):
        raise pc.PCError('PS2 emitter cached source differs; preserve edits and choose a clean cache')
    hook=work/'dependencies.cmake';_dependencies(hook)
    build=work/'build'
    _run(['cmake','-S',source/'thirdparty/PS2Recomp','-B',build,
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_PROJECT_PS2RetroX_INCLUDE='+hook.as_posix(),
        '-DPS2X_BUILD_RUNTIME=OFF','-DPS2X_BUILD_TEST=OFF','-DPS2X_BUILD_ANALYZER=OFF','-DPS2X_BUILD_STUDIO=OFF',
        '-DBUILD_TESTING=OFF'],work,'Configure the pinned PS2 C++ emitter')
    _run(['cmake','--build',build,'--target','ps2_recomp','--config','Release','--parallel','2'],work,'Build the PS2 C++ emitter')
    binary=next((p for p in build.rglob('ps2_recomp.exe' if os.name=='nt' else 'ps2_recomp') if p.is_file() and '_deps' not in p.parts),None)
    if binary is None:raise pc.PCError('the PS2 static emitter was not built')
    return binary


def _read(path,inspection,name):
    if inspection['input_kind']=='ee-elf':return path.read_bytes()
    rec=next((f for f in inspection['files'] if f['path']==name and not f['directory']),None)
    if rec is None or rec['size']>media.MAX_PROGRAM:raise pc.PCError('PS2 profile module is missing or too large: '+name)
    from ..rom.psx import _Disc
    with path.open('rb') as stream:return _Disc(stream).read(rec['lba'],rec['size'])


def generate(project,root):
    path=Path(project['input']).resolve();inspection=media.inspect(path)
    pins=project.get('profile')
    reviewed=profile.load(pins,inspection['input']['sha256']) if pins else profile.known(inspection['input']['sha256'])
    if reviewed is None and inspection.get('overlays'):
        raise pc.PCError('this disc has streamed EE modules; supply a reviewed input-bound PS2 profile for every module')
    boot=inspection['program']['boot']
    boot=boot or ('boot.elf' if inspection['input_kind']=='ee-elf' else '')
    if not boot:raise pc.PCError('PS2 input has no boot program')
    rows=reviewed['modules'] if reviewed else [dict(path=boot)]
    if inspection['input_kind']=='ee-elf' and len(rows)!=1:raise pc.PCError('a standalone EE ELF has one input module')
    if rows[0]['path']!=boot:raise pc.PCError('PS2 profile must place the original boot executable first')
    prepared=[]
    for row in rows:
        original=_read(path,inspection,row['path'])
        if original[:4]==b'MWo3':original=modules.mwo3_elf(original)
        prepared.append((original,profile.module(original,row if reviewed else None)))
    if inspection['program']['entry'] not in {f['address'] for f in prepared[0][1]['functions']}:
        raise pc.PCError('PS2 profile must cover the ELF entry without a title-specific entry override')
    sdk,runtime_pins=_sdk();emitter=_emitter(sdk)
    for name in ('game/modules','native','tools','tests','LICENSES','runtime'):(root/name).mkdir(parents=True)
    vendor=root/'runtime/ps2';shutil.copytree(sdk,vendor)
    runtime_patch.patch_filesystem(vendor);runtime_patch.patch_disc_services(vendor);runtime_patch.patch_host(vendor)
    _dependencies(root/'native/dependencies.cmake')
    shutil.copyfile(vendor/'LICENSE',root/'LICENSES/PS2-runtime-GPL-3.0.txt')
    records=[];emissions=[]
    with tempfile.TemporaryDirectory(prefix='.ps2-emission-',dir=root.parent) as tmp:
        work=Path(tmp)
        for index,(original,mapping) in enumerate(prepared):
            folder=root/f'game/modules/module{index}';folder.mkdir()
            analysis=modules.typed_elf(original,mapping['code_ranges'])
            original_path=work/f'module{index}.elf';original_path.write_bytes(analysis)
            csv_path=work/f'module{index}.csv'
            with csv_path.open('w',newline='',encoding='utf-8') as out:
                writer=csv.writer(out);writer.writerow(['Name','Start','End','Size'])
                for f in mapping['functions']:writer.writerow([f['name'],hex(f['address']),hex(f['address']+f['size']),f['size']])
            q=lambda value:json.dumps(str(value),ensure_ascii=False)
            config=work/f'module{index}.toml'
            config.write_text('[general]\ninput = '+q(original_path.as_posix())+'\noutput = '+q(folder.as_posix())+
                '\nghidra_output = '+q(csv_path.as_posix())+'\nsingle_file_output = false\noutput_worker_threads = 1\n'+
                'patch_syscalls = false\npatch_cop0 = true\npatch_cache = true\nskip = []\nstubs = '+
                json.dumps([f'{s["name"]}@0x{s["address"]:08x}' for s in mapping['native_services']])+'\n',encoding='utf-8')
            output=_run([emitter,config],work,f'Translate PS2 module {index}')
            (folder/'generation.log').write_text(output,encoding='utf-8')
            counts=reports.generation_report(output,expected_functions=len(mapping['functions']),expected_services=len(mapping['native_services']))
            codegen.validate_native_services(folder,mapping['native_services'])
            runtime_patch.install_vu_header(folder)
            guards=codegen.guard_generated(folder,original,expected_functions=counts['processed'],
                function_ranges={f['address']:f['size'] for f in mapping['functions']},code_ranges=mapping['code_ranges'])
            records.append(registry.isolate(folder,guards))
            emissions.append(dict(module=rows[index]['path'],**counts,analysis_elf_sha256=hashlib.sha256(analysis).hexdigest(),
                native_services=mapping['native_services'],guards=guards))
    dispatch=registry.registry(records,root/'native/modules.cpp',project_root=root)
    # Recheck the complete identity before publishing source derived from it.
    if media.inspect(path)['input']!=inspection['input']:raise pc.PCError('PS2 owner input changed during export')
    files=[f for f in inspection['files'] if not f['directory']]
    extract=[]
    for rec in files:
        if rec['path']==boot or rec.get('role')=='iop-irx':
            raw=_read(path,inspection,rec['path']);extract.append({**rec,'sha256':hashlib.sha256(raw).hexdigest()})
    recipe=dict(schema='decomp.wtf.ps2-assets/v1',input=inspection['input'],kind='disc' if files else 'ee-elf',
        sector_size=inspection.get('sector_size',2048),sector_data_offset=inspection.get('sector_data_offset',0),extract=extract)
    medium=(reviewed or {}).get('disc_medium','dvd' if recipe['sector_size']==2048 else 'cd')
    if medium not in ('cd','dvd'):raise pc.PCError('PS2 profile disc_medium must be cd or dvd')
    recipe['disc_medium']=medium
    (root/'game/assets.json').write_text(json.dumps(recipe,indent=2)+'\n',encoding='utf-8')
    retained=dict(schema=profile.SCHEMA,input_sha256=inspection['input']['sha256'],
        modules=[dict(path=row['path'],**mapping) for row,(_,mapping) in zip(rows,prepared)],
        iop_native_modules=(reviewed or {}).get('iop_native_modules',[]),provenance=(reviewed or {}).get('provenance',{}),
        runtime_arena_bytes=(reviewed or {}).get('runtime_arena_bytes',65536),disc_medium=medium)
    (root/'game/profile.json').write_text(json.dumps(retained,indent=2)+'\n',encoding='utf-8')
    iop=(reviewed or {}).get('iop_native_modules',[])
    allowed={Path(name).name for name in inspection.get('iop_modules',[])}
    if not isinstance(iop,list) or any(not isinstance(n,str) or n not in allowed for n in iop):
        raise pc.PCError('PS2 profile native IOP module must occur in the inspected owner disc')
    arena=profile.number((reviewed or {}).get('runtime_arena_bytes',65536))
    if arena<16384 or arena>8*1024*1024 or arena%16:raise pc.PCError('PS2 runtime arena must be 16 KiB..8 MiB and 16-byte aligned')
    loaded_end=max(s['physical']+s['memory_size'] for s in inspection['program']['loads'] if s['region']=='ee-ram')
    _config(root,project,boot if files else 'boot.elf',files,recipe,iop,arena,loaded_end)
    for source,target in (('Project.cmake','CMakeLists.txt'),('host.cpp','native/main.cpp'),('extract_assets.py','tools/extract_assets.py'),
        ('disc_files.hpp','native/decomp_disc_files.hpp'),('utf8.manifest','native/utf8.manifest'),('service_probe.cpp','tests/services.cpp')):
        (root/target).write_text(_source(source),encoding='utf-8')
    (root/'.gitignore').write_text('/assets/\n/build*/\n/saves/\n/captures/\n/.ps2-assets-*/\n',encoding='utf-8')
    (root/'README.md').write_text(_source('README.project.md'),encoding='utf-8')
    manifest=dict(schema=pc.SCHEMA,platform='ps2',backend=dict(id=BACKEND_ID,revision=revision()),
        runtime=dict(id='ps2recomp-sdlgpu',revision=runtime_pins['archives'][0]['commit'],source_sha256=runtime_pins['source_sha256'],license='GPL-3.0'),
        execution_model='hybrid',fallback=dict(interpreter=True,runtime_compilation=False),
        interpreter=dict(ee=False,iop=True,vu=True),build=dict(system='cmake',target='ps2_pc'),
        inputs=[inspection['input']],code_generation=emissions,dispatch=dispatch,
        qualification=dict(experimental=True,retail=False,playthrough=False),presentation=pc.presentation(project['renderer'],gpu='vulkan'),files={})
    for file in provider.payload(root):manifest['files'][file.relative_to(root).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    (root/'pc-project.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def _config(root,project,boot,files,recipe,iop,arena,loaded_end):
    q=lambda text:json.dumps(text,ensure_ascii=False)
    lines=['#pragma once','#include <vector>','#include "decomp_disc_files.hpp"','namespace decomp_ps2_game {',
        'inline constexpr const char *title='+q(project['title'])+';',
        'inline constexpr const char *renderer='+q(project['renderer'])+';',
        'inline constexpr const char *boot='+q(boot)+';',
        'inline constexpr bool has_disc='+('true' if files else 'false')+';',
        f'inline constexpr unsigned sector_size={recipe["sector_size"]},data_skip={recipe["sector_data_offset"]};',
        f'inline constexpr unsigned disc_type={0x12 if recipe["disc_medium"]=="cd" else 0x14}u;',
        f'inline constexpr uint32_t runtime_arena_bytes={arena}u,loaded_end={loaded_end}u;',
        'inline const std::vector<decomp_ps2::disc::Entry> files={']
    lines += ['{'+q(f['path'])+f',{f["lba"]}ull,{f["size"]}ull'+'},' for f in files]
    lines += ['};','inline const std::vector<std::string> iop_modules={'+','.join(q(n) for n in iop)+'};','}']
    (root/'native/game_config.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def export(input,output,*,profile=None,title='',renderer='auto',log=None):
    pc.presentation(renderer,gpu='vulkan')
    token=_progress.set(log)
    evidence=[];evidence_token=_evidence.set(evidence)
    try:return pc.export_backend(dict(platform='ps2',input=str(input),profile=profile,title=title or Path(input).stem,renderer=renderer),Path(output),backend())
    except pc.PCError as error:
        if evidence:
            import uuid
            destination=Path(output);folder=destination.parent/(destination.name[:60]+'-diagnostics-'+uuid.uuid4().hex[:8])
            folder.mkdir()
            (folder/'error.txt').write_text(str(error)+'\n',encoding='utf-8')
            for n,(label,text) in enumerate(evidence):
                (folder/f'module-{n}.log').write_text(label+'\n'+text,encoding='utf-8')
            raise pc.PCError(str(error)+'\nDiagnostics retained: '+str(folder)) from error
        raise
    finally:_progress.reset(token);_evidence.reset(evidence_token)


def backend():return pc.Backend(BACKEND_ID,'ps2',revision(),generate,experimental=True)
