"""Owner-media to a standalone PS1 C/C++ repository with a pinned hardware runtime."""
from contextvars import ContextVar
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess

from .. import pc,toolchains
from . import codegen,media,runtime_patch

BACKEND_ID='psx-psxrecomp-experimental'
SDK_COMMIT='31df2e1e0e0a6525733e68ff70e72ecbef84bb09'
SDK_SHA256='31c90dbda3fa05732a499434f21a1afa68490b9d231aa789e4cef93fe2c893eb'
CODEGEN_HASH='115b1739'
_progress=ContextVar('psx_native_progress',default=None)
_GENERATED={'runtime/include/overlay_codegen_hash.h','.decompnet-toolchain.json'}


def _source(name):return resources.files(__package__).joinpath(name).read_text(encoding='utf-8')


def revision():
    digest=hashlib.sha256(SDK_COMMIT.encode())
    for name in ('__init__.py','media.py','codegen.py','host.hpp','runtime_patch.py','extract_assets.py','Project.cmake'):
        digest.update(name.encode()+b'\0'+_source(name).encode())
    return digest.hexdigest()


def _log(value):
    callback=_progress.get()
    if callback:callback(value)


def _run(command,what):
    _log(what+'...')
    try:result=subprocess.run(list(map(str,command)),capture_output=True,text=True,
        encoding='utf-8',errors='replace',timeout=1800)
    except subprocess.TimeoutExpired as error:raise pc.PCError(what+' timed out') from error
    if result.returncode:raise pc.PCError(what+' failed:\n'+(result.stdout+result.stderr)[-5000:])
    return result.stdout


def _payload(sdk):
    return sorted((p for p in sdk.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'
                   and p.relative_to(sdk).as_posix() not in _GENERATED),key=lambda p:p.relative_to(sdk).as_posix())


def _sdk():
    override=os.environ.get('DECOMP_PSX_SDK')
    try:sdk=Path(override).resolve() if override else toolchains.ensure('psxrecomp-sdk',log=_log)
    except toolchains.ToolchainError as error:raise pc.PCError(str(error)) from error
    digest=hashlib.sha256()
    for path in _payload(sdk):digest.update(path.relative_to(sdk).as_posix().encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    if digest.hexdigest()!=SDK_SHA256:raise pc.PCError('PS1 runtime source differs from the pinned archive; restore the SDK')
    return sdk


def _recompiler(sdk):
    override=os.environ.get('DECOMP_PSX_RECOMPILER')
    if override:binary=Path(override)
    else:
        build=sdk.parent/'.psx-native-builds'/SDK_COMMIT
        options=['cmake','-S',sdk/'recompiler','-B',build,'-DCMAKE_BUILD_TYPE=Release',
                 '-DBUILD_TESTING=OFF','-DPSXRECOMP_ENABLE_CHD=OFF']
        _run(options,'Configure the PS1 static emitter')
        _run(['cmake','--build',build,'--target','psxrecomp-game','--config','Release','--parallel','2'],
             'Build the PS1 static emitter')
        binary=next((p for p in (build/'psxrecomp-game',build/'psxrecomp-game.exe',build/'Release/psxrecomp-game.exe') if p.is_file()),None)
        if binary is None:raise pc.PCError('the native PS1 emitter was not built')
    if _run([binary,'--codegen-hash'],'Verify the PS1 emitter').strip()!=CODEGEN_HASH:
        raise pc.PCError('PS1 emitter code-generation revision differs from the pinned runtime')
    return binary


def generate(project,root):
    if 'discs' not in project:
        rows=project.get('native_inputs',[project])
        discs=[media.project_input(row,i+1) for i,row in enumerate(rows)]
        if len({d['identity'] for d in discs})!=len(discs):raise pc.PCError('the same disc content cannot appear twice')
        project=dict(platform='psx',discs=discs,title=project.get('title') or 'PS1 game',renderer=project.get('renderer','auto'))
    sdk=_sdk();recompiler=_recompiler(sdk)
    for folder in ('game','native','tools','runtime','LICENSES'):(root/folder).mkdir()
    _log('Copying the pinned PS1 hardware runtime and license sources...')
    vendor=root/'runtime/psxrecomp';vendor.mkdir()
    for path in _payload(sdk):
        output=vendor/path.relative_to(sdk);output.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,output)
    runtime_patch.patch(vendor)
    (root/'LICENSES/decomp.wtf-MIT.txt').write_text(resources.files('decompnet.nds_pc').joinpath('runtime.LICENSE').read_text(encoding='utf-8'),encoding='utf-8')
    shutil.copyfile(vendor/'LICENSE',root/'LICENSES/PSXRecomp.txt')
    shutil.copyfile(vendor/'bios/OpenBIOS.LICENSE',root/'LICENSES/OpenBIOS-MIT.txt')
    modules=[]
    for disc in project['discs']:
        for index,item in enumerate([disc,*disc.get('modules',[])]):
            folder=root/f'game/disc{disc["index"]}'
            if index:folder=folder/f'module{index}'
            item={**item,'module_index':len(modules)+1}
            modules.append(codegen.module(recompiler,item,folder,_run,sdk))
    codegen.registry(modules,root/'native/modules.c')
    (root/'native/defaults.hpp').write_text('#pragma once\ninline constexpr bool decomp_default_require_gpu='+
        ('true' if project['renderer']=='opengl' else 'false')+';\n',encoding='utf-8')
    for source,target in (('host.hpp','native/decomp_host.hpp'),('Project.cmake','CMakeLists.txt'),
                          ('extract_assets.py','tools/extract_assets.py')):
        (root/target).write_text(_source(source),encoding='utf-8')
    discs=project['discs'];first=discs[0];info=first['info']
    recipe=dict(schema='decomp.wtf.ps1-assets/v1',discs=[dict(index=d['index'],kind=d['kind'],files=d['files']) for d in discs])
    (root/'game/assets.json').write_text(json.dumps(recipe,indent=2)+'\n',encoding='utf-8')
    q=lambda value:json.dumps(value,ensure_ascii=False)
    toml=['[game]','name = '+q(project['title']),'id = '+q(info['game_code']),
          'exe = '+q('game/disc1/'+Path(first['boot']).name),'players = 2',
          'discs = '+q([d['asset'] for d in discs]),'disc_serials = '+q([d['info']['game_code'] for d in discs]),
          'load_address = '+q(hex(info['load'])),'entry_pc = '+q(hex(info['entrypoint'])),
          'text_size = '+q(hex(len(first['image'])-2048)),
          '\n[recompiler]','seeds = "game/disc1/seeds.txt"','out_dir = "game"','strict = true',
          '\n[runtime]','window_title = '+q(project['title']),'memcard_dir = "saves"',
          '\n[video]','renderer = '+q('software' if project['renderer']=='software' else 'opengl'),
          'internal_resolution = "display"','supersample = 1.0','dynamic_resolution = false']
    (root/'game.toml').write_text('\n'.join(toml)+'\n',encoding='utf-8')
    (root/'.gitignore').write_text('/assets/\n/build*/\n/saves/\n/captures/\n/.psx-assets-*/\n',encoding='utf-8')
    (root/'README.md').write_text(_readme(project),encoding='utf-8')
    manifest=dict(schema=pc.SCHEMA,platform='psx',backend=dict(id=BACKEND_ID,revision=revision()),
        runtime=dict(id='psxrecomp',revision=SDK_COMMIT,upstream_source_sha256=SDK_SHA256,
            integration_revision=revision(),license='PolyForm-Noncommercial-1.0.0'),
        execution_model='hybrid',build=dict(system='cmake',target='ps1_pc'),
        fallback=dict(interpreter=True,runtime_compilation=False),qualification=dict(experimental=True,retail=False),
        inputs=[dict(sha256=d['files'][0]['sha256'],disc=d['index'],identity=d['identity'],files=d['files']) for d in discs],
        code_generation=modules,presentation=pc.presentation(project['renderer']),files={})
    for path in sorted(root.rglob('*')):
        if path.is_file():manifest['files'][path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'pc-project.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def _readme(project):
    return '''# PS1 native PC source project

This repository contains generated native game C, a source-shipped PS1 hardware
runtime, OpenGL geometry rendering, audio, input, CD-ROM and memory-card support.
The ordered disc set shares one executable and saves. No retail BIOS is needed:
the bundled OpenBIOS is MIT-licensed. The optional PSXRecomp runtime and generated
helpers have PolyForm Noncommercial 1.0.0 terms; see runtime/psxrecomp/LICENSE.
decomp.wtf's integration remains MIT. This output has experimental compatibility.

The execution model is hybrid: recognized original code runs as generated C;
unresolved/self-modified code uses the R3000 interpreter. No guest-code compiler
runs during play. The run report exposes native dispatch and interpreted counts.
Source matching and readable C recovery are separate from native execution.

## Build and run

Install [Python 3.12+](https://www.python.org/downloads/),
[CMake 3.24+](https://cmake.org/download/) and a native C/C++ compiler. Windows uses
[Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
with Desktop development with C++; Linux uses GCC or Clang. CMake downloads and
checks the pinned SDL3, libchdr and libwebp dependencies automatically.
Linux desktop builds need X11/OpenGL development packages:

```sh
sudo apt-get install build-essential libx11-dev libxext-dev libxcursor-dev libxi-dev libxfixes-dev libxrandr-dev libxss-dev libxtst-dev libasound2-dev libgl-dev libegl-dev
python tools/extract_assets.py /path/to/disc1.cue /path/to/disc2.cue
cmake -S . -B build
cmake --build build --config Release --parallel 2
```

Pass exactly the original inputs recorded in game/assets.json, in order; a
single-disc game takes one argument. CUE inputs retain every audio/data track.
The helper checks hashes before staging, preserves existing assets and requires
only Python's standard library. Source and saves survive restaging failures.

Run build/ps1_pc (Linux) or build/Release/ps1_pc.exe (Visual Studio). F11 switches
native-monitor fullscreen; resize/move the window to change its physical drawable
resolution, including HiDPI. OpenGL rasterizes the game's primitives at an
adaptive internal resolution and presents at the drawable size. F9/F10 insert
the previous/next disc through the actual tray-change path. Use this when the
game requests a disc change. Keyboard/gamepad mapping is in config.ini; memory
cards live under saves. Keep them when updating the source project.

Useful options: --renderer auto|opengl|software, --resolution WIDTHxHEIGHT,
--fullscreen, --headless, --frames N, --report result.json, --capture picture.ppm.
Explicit OpenGL requires a working context; automatic mode reports a software
fallback. Headless checks use --renderer software (also when the export default
explicitly requires OpenGL). Bounded validation can
also observe RAM with --observe ADDRESS, switch discs with --switch-disc FRAME:N,
or resize with --resize FRAME:WIDTHxHEIGHT. A full playthrough is a separate
acceptance step; a build or boot does not certify every game's compatibility.
'''


def _prepare(inputs,*,title='',renderer='auto'):
    pc.presentation(renderer)
    from ..rom.errors import RomError
    try:discs=media.prepare(inputs)
    except RomError as error:raise pc.PCError(str(error)) from error
    return dict(platform='psx',discs=discs,title=title or discs[0]['path'].stem,renderer=renderer)


def export(inputs,output,*,title='',renderer='auto',log=None):
    project=_prepare(inputs,title=title,renderer=renderer)
    token=_progress.set(log)
    try:return pc.export_backend(project,Path(output),backend())
    finally:_progress.reset(token)


def backend():return pc.Backend(BACKEND_ID,'psx',revision(),generate,experimental=True)
