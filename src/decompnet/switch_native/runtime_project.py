"""Source export for host-linked ExeFS modules and bounded Horizon services."""
import hashlib
import json
from pathlib import Path
import shutil

from .. import pc
from . import ROOT, discovery, emit, exefs, provider, revision

BACKEND_ID = 'switch-nxport-las-module-runtime'


def generate(project, root):
    path = Path(project['input'])
    inspection = exefs.load(path, include_images=True)
    binary = provider.build()
    game, runtime, assets = (root / name for name in ('game', 'runtime', 'assets'))
    for folder in (game, runtime, assets):
        folder.mkdir()
    registry = ['#include "runtime_api.h"\n']
    layouts = []
    for i, module in enumerate(inspection['modules']):
        image = module.pop('image')
        image_path = assets / (module['name'] + '.bin')
        image_path.write_bytes(image)
        roots = sorted(set(module['roots']) | set(discovery.entries(image, module)))
        module['discovered_entries'] = roots
        entries = root / (module['name'] + '-entries.txt')
        entries.write_text(''.join(str(p) + '\n' for p in roots))
        prefix = 'guest' + str(i)
        emit(binary, image_path, module, entries, game, root / (module['name'] + '-translation.json'), name=prefix)
        registry += [f'extern const uint64_t {prefix}_fn_addrs[], {prefix}_fn_count;\n',
                     f'extern const GuestFn {prefix}_fn_ptrs[];\n']
        text, data = module['segments'][0], module['segments'][2]
        fields = [module['base'], module['image_size'], text['offset'], text['size'], data['offset'], data['size']]
        layouts.append('{"' + module['name'] + '","' + image_path.name + '","' + hashlib.sha256(image).hexdigest() + '",' +
            ','.join(str(value) + 'ull' for value in fields) + ',' +
            f'{prefix}_fn_addrs,{prefix}_fn_ptrs,&{prefix}_fn_count' + '}')
    registry.append('const SwitchModule switch_modules[MODULE_COUNT]={' + ',\n'.join(layouts) + '};\n')
    registry.append('const uint64_t switch_initializer_count=' + str(len(inspection['initializers'])) + ';\n')
    registry.append('const uint64_t switch_initializers[]={' +
                    ','.join(str(p) + 'ull' for p in inspection['initializers'] or [0]) + '};\n')
    (runtime / 'modules.c').write_text(''.join(registry))
    constants = dict(MODULE_COUNT=len(inspection['modules']), IMAGE_ENTRY=inspection['entry'],
                     STACK_BASE=0x7200000000, STACK_SIZE=inspection['stack_size'],
                     HEAP_BASE=0x7300000000, HEAP_SIZE=0x400000, TLS_BASE=0x7400000000)
    layout = '#pragma once\n' + ''.join(f'#define {k} {v}ull\n' for k, v in constants.items())
    layout += '#define INPUT_SHA256 "' + inspection['input']['sha256'] + '"\n'
    (runtime / 'layout.h').write_text(layout)
    for source, target in (('runtime.c', runtime / 'runtime.c'), ('kernel.c', runtime / 'kernel.c'),
            ('runtime_api.h', runtime / 'runtime_api.h'), ('integrity.cpp', runtime / 'integrity.cpp'),
            ('code_guard.h', runtime / 'code_guard.h'), ('Runtime.cmake', root / 'CMakeLists.txt'),
            ('README.runtime.md', root / 'README.md'), ('sources.json', root / 'sources.json'),
            ('THIRD_PARTY.md', root / 'THIRD_PARTY.md'), ('MIT.Kirikae.txt', root / 'MIT.Kirikae.txt')):
        shutil.copyfile(ROOT / source, target)
    shutil.copyfile(ROOT.parent / 'nds_native/hash.hpp', runtime / 'hash.hpp')
    for name in ('LICENSE', 'LICENSE-LASRecomp'):
        shutil.copyfile(ROOT / 'vendor/nxport-lifter' / name, root / (name + '.nxport.txt'))
    (root / 'analysis.json').write_text(json.dumps(inspection, indent=2) + '\n')
    if exefs.identify_inputs(path) != inspection['inputs']:
        raise pc.PCError('Switch ExeFS inputs changed during generation')
    manifest = dict(schema=pc.SCHEMA, platform='switch', output_kind='cpu-probe',
        backend=dict(id=BACKEND_ID, revision=revision()), execution_model='static-recompiled',
        runtime=dict(id='switch-host-linked-service-development', revision=revision()),
        inputs=inspection['inputs'], build=dict(system='cmake', target='switch_runtime'),
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(root.rglob('*')) if p.is_file()},
        fallback=dict(interpreter=False, runtime_compilation=False),
        qualification=dict(graphics=False, retail=False, kernel_services=True,
            service_scope='single-thread heap, thread ID, debug and SM/settings CMIF subset',
            guest_thread_creation=False, audio=False, saves=False))
    (root / 'pc-project.json').write_text(json.dumps(manifest, indent=2) + '\n')


def export(path, destination):
    path = Path(path).resolve()
    exefs.load(path)
    if Path(destination).resolve().is_relative_to(path):
        raise pc.PCError('Switch runtime output must stay outside the original ExeFS directory')
    backend = pc.Backend(BACKEND_ID, 'switch', revision(), generate, experimental=True)
    return pc.export_backend(dict(platform='switch', input=str(path), root=str(path)), destination, backend)
