"""3DS native source development: validated images and independent CPU probes.

The prototype is deliberately separate from advertised game-output backends
until a source-shipped GPU and service runtime passes original fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from .. import pc, toolchains
from . import media, provider

BACKEND_ID = '3ds-3dsrecomp-cpu-probe'


def revision():
    value = hashlib.sha256()
    for path in sorted(Path(__file__).parent.iterdir(), key=lambda p:p.name):
        if path.suffix in ('.py','.rs','.cpp','.cmake','.md'):
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
    inspection = media.load(path, include_code=True)
    code = inspection.pop('code')
    rustc = os.environ.get('DECOMP_3DS_RUSTC') or shutil.which('rustc')
    if not rustc:
        raise pc.PCError('3DS source export needs Rust 1.88+: https://www.rust-lang.org/tools/install . Generated CPU projects build with CMake and C/C++ only.')
    sdk = Path(os.environ.get('DECOMP_3DS_SDK') or toolchains.root()/'3dsrecomp-sdk').resolve()
    if not sdk.exists():
        provider.download(sdk)
    key = hashlib.sha256((provider.SOURCE_SHA256+revision()).encode()).hexdigest()[:16]
    emitter = provider.build(sdk, sdk.parent/('3ds-emitter-'+key), rustc)
    game, runtime, assets = root/'game', root/'runtime', root/'assets'
    for folder in (game,runtime,assets):
        folder.mkdir()
    text = inspection['segments'][0]
    text_file = assets/'text.bin'
    text_file.write_bytes(code[:text['size']])
    seeds = root/'entries.txt'
    seeds.write_text(str(inspection['entry'])+'\n')
    try:
        result = subprocess.run([str(emitter), str(text_file), str(text['address']), str(seeds), str(game)],
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
    with path.open('rb') as stream:
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
