"""3DS native source development: validated images, CPU and source runtime probes.

The prototype is deliberately separate from advertised game-output backends
until retail module coverage and the full presentation/audio/input path qualify.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from .. import pc, toolchains
from . import media, provider

BACKEND_ID = '3ds-3dsrecomp-cpu-probe'


def revision():
    value = hashlib.sha256()
    for path in sorted(Path(__file__).parent.iterdir(), key=lambda p:p.name):
        if path.suffix in ('.py','.rs','.cpp','.cmake','.md','.lock','.toml'):
            value.update(path.name.encode()+b'\0'+path.read_bytes())
    value.update(Path(__file__).parents[1].joinpath('nds_native/hash.hpp').read_bytes())
    return value.hexdigest()


def _portable(files):
    """Keep the pinned emitter's C usable with Visual Studio as well as GCC."""
    header = files/'recomp.h'
    text = header.read_text()
    portability = '''#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#define LIKELY(x) (!!(x))
#define UNLIKELY(x) (!!(x))
#define ALWAYS_INLINE __forceinline
#define CTR_COLD __declspec(noinline)
#define __builtin_bswap32 _byteswap_ulong
static inline unsigned ctr_clz(uint32_t x) { unsigned long at; return _BitScanReverse(&at,x)?31u-at:32u; }
#define __builtin_clz ctr_clz
#else
#define LIKELY(x) __builtin_expect(!!(x), 1)
#define UNLIKELY(x) __builtin_expect(!!(x), 0)
#define ALWAYS_INLINE inline __attribute__((always_inline))
#define CTR_COLD __attribute__((noinline, cold))
#endif
'''
    old = '#define LIKELY(x) __builtin_expect(!!(x), 1)\n#define UNLIKELY(x) __builtin_expect(!!(x), 0)'
    if text.count(old)!=1:
        raise pc.PCError('pinned 3DS ABI portability patch no longer applies')
    text = text.replace(old, portability).replace('#define ALWAYS_INLINE inline __attribute__((always_inline))\n\n/* the page', '\n/* the page')
    text = text.replace('static __attribute__((noinline, cold))', 'static CTR_COLD')
    header.write_text(text, encoding='utf-8', newline='\n')
    entries = files/'entries.c'
    text = entries.read_text().replace('recomp_modules[] = {\n};', 'recomp_modules[1] = {{0}};')
    entries.write_text(text, encoding='utf-8', newline='\n')


def generate(project, root):
    path = Path(project['input']).resolve()
    input_source = project.get('_source',path)
    inspection = media.load_source(input_source, include_code=True)
    code = inspection.pop('code')
    rustc = os.environ.get('DECOMP_3DS_RUSTC') or shutil.which('rustc')
    if not rustc:
        raise pc.PCError('3DS source export needs Rust 1.88+: https://www.rust-lang.org/tools/install . Generated CPU projects build with CMake and C/C++ only.')
    sdk = Path(os.environ.get('DECOMP_3DS_SDK') or toolchains.root()/'3dsrecomp-sdk').resolve()
    if not sdk.exists():
        provider.download(sdk)
    key = hashlib.sha256(provider.SOURCE_SHA256.encode()+Path(__file__).with_name('emitter.rs').read_bytes()).hexdigest()[:16]
    emitter = provider.build(sdk, sdk.parent/('3ds-emitter-'+key), rustc)
    game, runtime, assets = root/'game', root/'runtime', root/'assets'
    for folder in (game,runtime,assets):
        folder.mkdir()
    text = inspection['segments'][0]
    text_file = assets/'text.bin'
    text_file.write_bytes(code[:text['size']])
    seeds = root/'entries.txt'
    # Callback tables and vtables in either data segment are additional roots,
    # as in the upstream Image::into_program. They are discovery hints; they do
    # not bypass instruction validation or executable provenance guards.
    entries = {inspection['entry']}
    for segment in inspection['segments'][1:]:
        raw = code[segment['code_offset']:segment['code_offset']+segment['size']]
        for (word,) in struct.iter_unpack('<I', raw[:len(raw)//4*4]):
            if text['address'] <= (word & ~1) < text['address']+text['size']:
                entries.add(word)
    seeds.write_text('\n'.join(map(str,[inspection['entry'],*sorted(entries-{inspection['entry']})]))+'\n')
    if project.get('instruction_boundaries'):
        from . import romfs
        modules=romfs.modules(input_source,inspection)
        inspection['modules']=[]
        if modules:
            folder=assets/'modules';folder.mkdir()
            for index,module in enumerate(modules):
                name=f'{index:04}'+('.crs' if module['path'].lower().endswith('.crs') else '.cro')
                (folder/name).write_bytes(module.pop('data'))
                inspection['modules'].append({**module,'file':name})
    try:
        command = [str(emitter), str(text_file), str(text['address']), str(seeds), str(game)]
        if project.get('instruction_boundaries'):
            command.append('--instruction-boundaries')
            if inspection['modules']:
                command.extend(['--modules',str(assets/'modules')])
        result = subprocess.run(command,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise pc.PCError('3DS source generation could not complete: '+str(error)) from error
    if result.returncode:
        raise pc.PCError('3DS source generation failed:\n'+result.stderr[-6000:])
    _portable(game)
    layout = ['#pragma once', '#include <cstdint>',
              'struct Segment {const char* file;uint32_t address,size,allocated;bool writable;const char* sha256;};',
              'constexpr Segment segments[]={']
    for segment in inspection['segments']:
        data = code[segment['code_offset']:segment['code_offset']+segment['size']]
        name = segment['name']+'.bin'
        (assets/name).write_bytes(data)
        allocated = segment['memory_size']
        layout.append('{"'+name+'",'+f'{segment["address"]}u,{len(data)}u,{allocated}u,'+
                      ('true' if segment['access']=='rw' else 'false')+',"'+hashlib.sha256(data).hexdigest()+'"},')
    layout.extend(['};', f'constexpr uint32_t entry_point={inspection["entry"]}u;'])
    (runtime/'layout.hpp').write_text('\n'.join(layout)+'\n', encoding='utf-8')
    for source, target in ((Path(__file__).with_name('probe.cpp'), runtime/'probe.cpp'),
                           (Path(__file__).with_name('Project.cmake'), root/'CMakeLists.txt'),
                           (Path(__file__).parents[1]/'nds_native/hash.hpp', runtime/'hash.hpp'),
                           (Path(__file__).with_name('README.project.md'), root/'README.md')):
        shutil.copyfile(source, target)
    (root/'analysis.json').write_text(json.dumps(inspection, indent=2)+'\n')
    (root/'THIRD_PARTY.md').write_text('Generated ARM/Thumb/VFP C and recomp.h use the MIT-licensed 3dsrecomp emitter.\n'
        f'Source: https://github.com/fearkov/3dsrecomp/tree/{provider.COMMIT}\n'
        'License declaration: Cargo.toml and abi/Cargo.toml at that revision.\n'
        'Local changes: MSVC portability macros and a nonempty sentinel for the empty module table.\n')
    shutil.copyfile(Path(__file__).with_name('MIT.3dsrecomp.txt'), root/'MIT.3dsrecomp.txt')
    with input_source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest()!=inspection['input']['sha256']:
            raise pc.PCError('3DS owner input changed during source generation')
    files = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file()}
    manifest = dict(schema=pc.SCHEMA, platform='3ds', output_kind='cpu-probe',
                    backend=dict(id=BACKEND_ID, revision=revision()), execution_model='static-recompiled',
                    runtime=dict(id='ctr-bounded-cpu-harness', revision=revision()),
                    inputs=[inspection['input']], build=dict(system='cmake', target='ctr_probe'),
                    files=files, fallback=dict(interpreter=False, runtime_compilation=False),
                    qualification=dict(graphics=False, retail=False, kernel_services=False, audio=False, saves=False))
    (root/'pc-project.json').write_text(json.dumps(manifest, indent=2)+'\n')


def probe_backend():
    return pc.Backend(BACKEND_ID, '3ds', revision(), generate, experimental=True)


def export_probe(path, destination):
    return pc.export_backend(dict(platform='3ds', input=str(path)), destination, probe_backend())


RUNTIME_BACKEND_ID = '3ds-zakuro-service-probe'


def generate_runtime(project, root):
    from . import runtime_patch, runtime_provider
    screen_mode=project.get('screen_mode','dual')
    if screen_mode not in ('dual','unified'):
        raise pc.PCError('3DS screen mode must be dual or unified')
    generate({**project, 'instruction_boundaries':True}, root)
    inspection = json.loads((root/'analysis.json').read_text())
    sdk = Path(os.environ.get('DECOMP_3DS_RUNTIME_SDK') or toolchains.root()/'3ds-runtime-sdk').resolve()
    if not sdk.exists():
        runtime_provider.download(sdk, recompiler=os.environ.get('DECOMP_3DS_SDK'))
    pins = runtime_provider.verify(sdk)
    native = root/'native'
    native.mkdir()
    for name in ('runtime','recompiler'):
        shutil.copytree(sdk/name, native/name)
    runtime_patch.apply(native)
    app = native/'app'
    (app/'src').mkdir(parents=True)
    package = Path(__file__).parent
    for source, target in ((package/'Runtime.Cargo.toml',app/'Cargo.toml'),
                           (package/'Runtime.lock',app/'Cargo.lock'),
                           (package/'runtime_build.rs',app/'build.rs'),
                           (package/'runtime_main.rs',app/'src/main.rs'),
                           (package/'desktop.rs',app/'src/desktop.rs'),
                           (package/'gamepad.rs',app/'src/gamepad.rs'),
                           (package/'gpu_scenes.rs',app/'src/gpu_scenes.rs'),
                           (package/'module_scenes.rs',app/'src/module_scenes.rs'),
                           (package/'Runtime.cmake',root/'CMakeLists.txt'),
                           (package/'README.runtime.md',root/'README.md')):
        shutil.copyfile(source,target)
    from .runtime_audio import install as install_audio
    install_audio(native,app)
    (app/'src/identity.rs').write_text(
        f'const TITLE_ID:u64=0x{inspection["program_id"]};\n'
        f'const INPUT_SHA256:&str="{inspection["input"]["sha256"]}";\n'
        f'const INPUT_SIZE:u64={inspection["input"]["size"]};\n',encoding='utf-8')
    with (app/'src/identity.rs').open('a',encoding='utf-8') as file:
        file.write(f'const DEFAULT_UNIFIED:bool={str(screen_mode=="unified").lower()};\n')
    # The earlier, minimal CPU harness is superseded by the bundled core here.
    shutil.rmtree(root/'runtime')
    (root/'runtime-sources.json').write_text(json.dumps(pins,indent=2)+'\n',encoding='utf-8')
    with (root/'THIRD_PARTY.md').open('a',encoding='utf-8') as file:
        file.write(f'\nThe bundled MIT kernel/services/PICA runtime is Zakuro at {runtime_provider.COMMIT}.\n'
            f'Source: https://github.com/fearkov/zakuro/tree/{runtime_provider.COMMIT}\n'
            'Its license is native/runtime/LICENSE. Integration changes are in this generated source: '
            'local ABI paths, strict missing-code/instruction guards, explicit unknown-service errors, '
            'adaptive raster resolution and unified screen composition. Host crates and checksums '
            'are locked in native/app/Cargo.lock.\n')
    manifest = json.loads((root/'pc-project.json').read_text())
    manifest.update(backend=dict(id=RUNTIME_BACKEND_ID,revision=revision()),
        execution_model='hybrid', runtime=dict(id='zakuro-core',revision=runtime_provider.COMMIT,license='MIT'),
        fallback=dict(interpreter=True,runtime_compilation=False,default='strict'),
        development_presentation=dict(screens=2,screen_mode=screen_mode,modes=['dual','unified'],
            resolution='drawable',continuous_scene_qualified=False),
        build=dict(system='cmake',target='ctr_runtime'))
    manifest['qualification'].update(kernel_services=True)
    manifest['files'] = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(root.rglob('*')) if p.is_file() and p.name!='pc-project.json'}
    (root/'pc-project.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def runtime_backend():
    return pc.Backend(RUNTIME_BACKEND_ID,'3ds',revision(),generate_runtime,experimental=True)


def export_runtime(path, destination, *, screen_mode='dual', source=None):
    project=dict(platform='3ds',input=str(path),screen_mode=screen_mode)
    if source is not None:
        project['_source']=source
    return pc.export_backend(project,destination,runtime_backend())
