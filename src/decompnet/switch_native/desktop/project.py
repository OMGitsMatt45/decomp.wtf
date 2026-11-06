"""Static C source export with the complete Switch desktop host services."""
import hashlib
import json
from pathlib import Path
import shutil
import struct

from ... import pc
from .. import ROOT, discovery, emit, exefs, media, provider, revision
from . import sdk

BACKEND_ID = 'switch-nxport-las-kirikae-native'


def inspect(path, *, images=False):
    path = Path(path)
    if path.is_dir():
        return exefs.load(path, include_images=images)
    module = media.load(path, include_image=images)
    if module['format'] == 'nso':
        return exefs.load(path, include_images=images, single=True)
    # Homebrew normally links at the Horizon ASLR base; ExeFS is independently
    # relocated by the host linker. Preserve the probe's original fixed layout.
    module.update(name='main', base=0x08000000, entry=0x08000000, roots=[0x08000000])
    return dict(platform='switch', format=module['format'], input=module['input'], inputs=[module['input']],
                entry=module['entry'], stack_size=0x100000, modules=[module], initializers=[])


def snapshot(path, romfs=None, *, images=False):
    result = inspect(path, images=images)
    if romfs:
        romfs = Path(romfs)
        if romfs.is_symlink() or not romfs.is_file() or not 0x50 <= romfs.stat().st_size <= 32 * 1024**3:
            raise pc.PCError('Switch --romfs needs a regular extracted RomFS image of 80 bytes to 32 GiB')
        with romfs.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result['inputs'].append(dict(name=romfs.name, size=romfs.stat().st_size, sha256=digest))
        result['input'] = dict(result['input'], sha256=hashlib.sha256(json.dumps(
            result['inputs'], sort_keys=True, separators=(',', ':')).encode()).hexdigest())
    return result


def generate(project, root):
    path = Path(project['input'])
    romfs = project.get('switch_romfs')
    inspection = snapshot(path, romfs, images=True)
    binary = provider.build(desktop=True)
    game, runtime, assets = (root / name for name in ('game', 'runtime', 'assets'))
    for folder in (game, runtime, assets):
        folder.mkdir()
    sdk.export(root / 'sdk')
    registry = ['#include "native_api.h"\n']
    layouts = []
    feedback = project.get('switch_entries', [])
    for i, module in enumerate(inspection['modules']):
        image = module.pop('image')
        image_path = assets / (module['name'] + '.bin')
        image_path.write_bytes(image)
        text, ro, data = module['segments']
        lo, hi = module['base'] + text['offset'], module['base'] + text['offset'] + text['size']
        roots = set(module['roots']) | set(discovery.entries(image, module))
        # Relocated code pointers in initialized data/vtables supplement ADR roots.
        for segment in (ro, data):
            start = (segment['offset'] + 7) & ~7
            end = segment['offset'] + segment['size']
            for offset in range(start, end - 7, 8):
                address = struct.unpack_from('<Q', image, offset)[0]
                if lo <= address < hi and address % 4 == 0:
                    roots.add(address)
        roots.update(p for p in feedback if lo <= p < hi)
        module['discovered_entries'] = sorted(roots)
        entries = root / (module['name'] + '-entries.txt')
        entries.write_text(''.join(str(p) + '\n' for p in sorted(roots)))
        prefix = 'guest' + str(i)
        emit(binary, image_path, module, entries, game, root / (module['name'] + '-translation.json'), name=prefix, desktop=True)
        registry += [f'extern const uint64_t {prefix}_fn_addrs[], {prefix}_fn_count;\n',
                     f'extern const GuestFn {prefix}_fn_ptrs[];\n']
        fields = [module['base'], len(image), text['offset'], text['size'], ro['offset'], ro['size'],
                  data['offset'], data['size'], module['bss_size']]
        layouts.append('{' + ','.join(json.dumps(v) for v in (module['name'], image_path.name, hashlib.sha256(image).hexdigest())) + ',' +
            ','.join(str(value) + 'ull' for value in fields) + ',' +
            f'{prefix}_fn_addrs,{prefix}_fn_ptrs,&{prefix}_fn_count' + '}')
    registry.append('static const SwModule modules[]={' + ',\n'.join(layouts) + '};\n')
    registry.append('size_t sw_module_count(void){return sizeof(modules)/sizeof(*modules);}\n')
    registry.append('const SwModule *sw_module_at(size_t i){return &modules[i];}\n')
    registry.append('static const uint64_t initializers[]={' + ','.join(str(p) + 'ull' for p in inspection['initializers'] or [0]) + '};\n')
    registry.append('const uint64_t *sw_initializers(size_t *n){*n=' + str(len(inspection['initializers'])) + ';return initializers;}\n')
    startup = inspection.get('startup') or {}
    registry.append(f'uint64_t sw_sdk_startup(void){{return {startup.get("entry", 0)}ull;}}\n')
    for name, values in (('sdk_initializers', startup.get('sdk_initializers', [])),
                         ('main_initializers', startup.get('main_initializers', [])),
                         ('sdk_finalizers', startup.get('finalizers'))):
        if values is None:
            registry.append(f'const uint64_t *sw_{name}(size_t *n){{*n=0;return NULL;}}\n')
            continue
        registry.append(f'static const uint64_t {name}[]={{' +
                        ','.join(str(p) + 'ull' for p in values or [0]) + '};\n')
        registry.append(f'const uint64_t *sw_{name}(size_t *n){{*n={len(values)};return {name};}}\n')
    title = int(inspection['input']['sha256'][:16], 16)
    if path.is_dir():
        _, _, npdm = exefs.files(path)
        if npdm:
            raw = npdm.read_bytes()
            offset = struct.unpack_from('<I', raw, 0x70)[0]
            if offset + 0x18 <= len(raw) and raw[offset:offset + 4] == b'ACI0':
                title = struct.unpack_from('<Q', raw, offset + 0x10)[0]
    romfs_sha = ''
    if romfs:
        romfs = Path(romfs)
        shutil.copyfile(romfs, assets / 'romfs.bin')
        with (assets / 'romfs.bin').open('rb') as stream:
            romfs_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if romfs_sha != inspection['inputs'][-1]['sha256']:
            raise pc.PCError('Switch RomFS changed during source export')
    for name, value in dict(entry=inspection['entry'], stack_size=inspection['stack_size'], title_id=title).items():
        registry.append(f'uint64_t sw_{name}(void){{return {value}ull;}}\n')
    for name, value in dict(input_sha256=inspection['input']['sha256'], backend_revision=revision(), romfs_sha256=romfs_sha).items():
        registry.append('const char *sw_' + name + '(void){return ' + json.dumps(value) + ';}\n')
    (runtime / 'modules.c').write_text(''.join(registry))
    (runtime / 'layout.h').write_text('#pragma once\n')
    for name in ('native_api.h', 'bridge.c', 'main.c'):
        shutil.copyfile(sdk.ROOT / name, runtime / name)
    for name, target in (('Project.cmake', 'CMakeLists.txt'), ('README.md', 'README.md')):
        shutil.copyfile(sdk.ROOT / name, root / target)
    for name in ('sources.json', 'THIRD_PARTY.md', 'MIT.Kirikae.txt'):
        shutil.copyfile(ROOT / name, root / name)
    shutil.copyfile(ROOT / 'integrity.cpp', runtime / 'integrity.cpp')
    shutil.copyfile(ROOT.parent / 'nds_native/hash.hpp', runtime / 'hash.hpp')
    for name in ('LICENSE', 'LICENSE-LASRecomp'):
        shutil.copyfile(ROOT / 'vendor/nxport-lifter' / name, root / (name + '.nxport.txt'))
    (root / 'analysis.json').write_text(json.dumps(inspection, indent=2) + '\n')
    original = snapshot(path, romfs)
    if inspection['inputs'] != original['inputs']:
        raise pc.PCError('Switch input changed during source export')
    manifest = dict(schema=pc.SCHEMA, platform='switch', output_kind='cpu-probe',
        backend=dict(id=BACKEND_ID, revision=revision()), execution_model='static-recompiled',
        runtime=dict(id='switch-kirikae-native-desktop', revision=revision()),
        inputs=inspection['inputs'], build=dict(system='cmake', target='switch_native'),
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(root.rglob('*')) if p.is_file()},
        fallback=dict(interpreter=False, runtime_compilation=False),
        qualification=dict(graphics=False, retail=False, kernel_services=True, guest_thread_creation=True,
            graphics_runtime='Maxwell to SPIR-V and Vulkan; desktop geometry qualification pending',
            audio='source-shipped Kirikae audout/audren', saves='source-shipped title-isolated filesystem'))
    (root / 'pc-project.json').write_text(json.dumps(manifest, indent=2) + '\n')


def export(path, destination, *, romfs=None, feedback=()):
    path = Path(path).resolve()
    inspection = snapshot(path, romfs)
    if path.is_dir() and Path(destination).resolve().is_relative_to(path):
        raise pc.PCError('Switch output must stay outside the original ExeFS directory')
    entries = set()
    for file in feedback:
        if Path(file).stat().st_size > 4 * 1024 * 1024:
            raise pc.PCError('Switch feedback report exceeds 4 MiB')
        data = json.loads(Path(file).read_text())
        if data.get('schema') != 'decomp.wtf.switch-native-run/v1' or data.get('input_sha256') != inspection['input']['sha256']:
            raise pc.PCError('Switch feedback must identify this exact input snapshot')
        for event in data.get('failures', []):
            if event.get('kind') == 'missing-native-target':
                address = event.get('pc')
                if type(address) is not int or address % 4:
                    raise pc.PCError('invalid Switch feedback address')
                if not any(m['base'] <= address < m['base'] + m['segments'][0]['size'] for m in inspection['modules']):
                    raise pc.PCError('Switch feedback target is outside the input code; dynamically loaded code requires a new source input')
                entries.add(address)
    backend = pc.Backend(BACKEND_ID, 'switch', revision(), generate, experimental=True)
    return pc.export_backend(dict(platform='switch', input=str(path), switch_romfs=str(Path(romfs).resolve()) if romfs else None,
                                  switch_entries=sorted(entries)), destination, backend)
