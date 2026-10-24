"""Experimental, reviewed-profile DS static PC repository generation.

This is explicitly invoked and deliberately absent from pc.BACKENDS: retail
hardware/runtime support is not qualified by the original execution fixture.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from importlib import resources
import inspect
import json
from pathlib import Path
import struct

from .. import pc
from ..rom.nds_modules import NdsImage, decompress_blz, MAX_MODULE_SIZE
from .translate import TranslationError, translate, u

SCHEMA = 'decomp.wtf.nds-static-profile/v1'
BACKEND_ID = 'nds-static-experimental'
REGIONS = ((0x02000000, 0x02400000), (0x03000000, 0x03008000), (0x03800000, 0x03810000))
MAX_INSTRUCTIONS = 200000


def _source(name):
    return resources.files(__package__).joinpath(name).read_text(encoding='utf-8')


def revision():
    digest = hashlib.sha256()
    for name in ('__init__.py','translate.py','runtime.hpp','runtime.cpp','main.cpp','extract.py','runtime.LICENSE'):
        digest.update(name.encode()+b'\0'+_source(name).encode())
    digest.update(inspect.getsource(decompress_blz).encode())
    digest.update(str(MAX_MODULE_SIZE).encode())
    return digest.hexdigest()


def _integer(value, what, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 0xffffffff:
        raise TranslationError(what+' must be a '+('positive ' if positive else '')+'32-bit integer')
    return value


def _memory(address, size):
    return any(lo <= address and address+size <= hi for lo, hi in REGIONS)


def prepare(data: bytes, profile: dict):
    if not isinstance(profile, dict) or profile.get('schema') != SCHEMA:
        raise TranslationError('unsupported DS static profile schema')
    if profile.get('input_sha256') != hashlib.sha256(data).hexdigest():
        raise TranslationError('profile ROM SHA-256 differs from the original input')
    image = NdsImage(data)
    main = image.modules['arm9']
    if main.offset >= 0x4000:
        raise TranslationError('retail/secure-area ARM9 decoding is not integrated into this experimental adapter')
    processors = profile.get('processors')
    if not isinstance(processors, dict) or set(processors) != {'arm9','arm7'}:
        raise TranslationError('profile must declare ARM9 and ARM7 initial stacks')
    entries, stacks = [], []
    for cpu, header in (('arm9',0x24),('arm7',0x34)):
        entry = struct.unpack_from('<I',data,header)[0]
        config = processors[cpu]
        if not isinstance(config,dict):
            raise TranslationError('invalid processor profile')
        sp = _integer(config.get('stack'),cpu+' stack',positive=True)
        if sp % 4 or not _memory(sp-4,4):
            raise TranslationError(cpu+' stack is outside supported RAM or unaligned')
        entries.append(entry);stacks.append(sp)
    reviewed = profile.get('code')
    if not isinstance(reviewed, dict) or not reviewed or set(reviewed)-set(image.modules):
        raise TranslationError('code ranges must identify known DS modules')
    selected = {name for name,m in image.modules.items() if m.overlay_id is None} | set(reviewed)
    modules, ranges, instruction_count = [], [], 0
    initial = []
    for name in sorted(selected):
        module = image.modules[name]
        if module.overlay_id is not None and module.overlay_id > 0xffffff:
            raise TranslationError('overlay ID exceeds the experimental runtime range')
        if module.ctor_start or module.ctor_end:
            raise TranslationError('overlay constructors need execution integration: '+name)
        bss_address = module.bss_address if module.bss_address is not None else module.address+module.code_size
        if not _memory(module.address,module.code_size) or module.bss_size and not _memory(bss_address,module.bss_size):
            raise TranslationError('module needs an unimplemented DS memory mapping: '+name)
        code = data[module.offset:module.offset+module.stored_size] if name=='arm9' else image.code(name)
        if len(code) != module.code_size:
            raise TranslationError('module needs additional decoding: '+name)
        extents=[(module.address,module.address+module.code_size)]
        if module.bss_size:extents.append((bss_address,bss_address+module.bss_size))
        if len(extents)>1 and extents[0][0]<extents[1][1] and extents[1][0]<extents[0][1]:
            raise TranslationError('module BSS overlaps initialized data')
        # Initial images share the physical memory bus and cannot silently replace one another.
        if module.overlay_id is None:
            if any(a<d and c<b for a,b in extents for c,d in initial):
                raise TranslationError('initial DS modules overlap in physical RAM')
            initial.extend(extents)
        record={**asdict(module),'size':len(code),'bss_address':bss_address,
                'compressed':bool(module.flags & 0x1000000),
                'asset':name.replace(':','_')+'.bin','sha256':hashlib.sha256(code).hexdigest(),
                'instructions':[]}
        declared = reviewed.get(name,[])
        if not isinstance(declared,list):
            raise TranslationError('module code ranges must be a list')
        taken=[]
        for item in declared:
            if not isinstance(item,dict):raise TranslationError('invalid code range')
            address=_integer(item.get('address'),'code address')
            size=_integer(item.get('size'),'code size',positive=True)
            if not module.address <= address < address+size <= module.address+len(code):
                raise TranslationError('code range lies outside its decoded module: '+name)
            if any(address<hi and lo<address+size for lo,hi in taken):
                raise TranslationError('overlapping code ranges in '+name)
            taken.append((address,address+size))
            offset=address-module.address
            translated=translate(code[offset:offset+size],address,item.get('mode'),module.cpu)
            instruction_count+=len(translated)
            if instruction_count>MAX_INSTRUCTIONS:
                raise TranslationError('experimental translation instruction limit exceeded')
            record['instructions'].extend(translated)
            ranges.append(dict(cpu=module.cpu,overlay=module.overlay_id,address=address,size=size,
                               expected=code[offset:offset+size]))
        modules.append(record)
    overlays=[m for m in modules if m['overlay_id'] is not None]
    for index,module in enumerate(overlays):
        extents=[(module['address'],module['address']+module['size'])]
        if module['bss_size']:
            extents.append((module['bss_address'],module['bss_address']+module['bss_size']))
        if any(a<d and c<b for a,b in extents for c,d in initial):
            raise TranslationError('overlay overlaps resident DS memory: '+module['name'])
        # Same-CPU overlays may reuse an address because only one is active.
        # Cross-CPU overlap needs a lifetime model rather than two active dispatchers.
        for other in overlays[:index]:
            if other['cpu']==module['cpu']:continue
            occupied=[(other['address'],other['address']+other['size'])]
            if other['bss_size']:
                occupied.append((other['bss_address'],other['bss_address']+other['bss_size']))
            if any(a<d and c<b for a,b in extents for c,d in occupied):
                raise TranslationError('overlays on different CPUs overlap physical RAM')
    for cpu,entry in zip(('arm9','arm7'),entries):
        resident=[m for m in modules if m['cpu']==cpu and m['overlay_id'] is None]
        if not any(i.address==entry&~1 and i.thumb==bool(entry&1) for m in resident for i in m['instructions']):
            raise TranslationError(cpu+' entry has no reviewed translation with the correct ARM/Thumb mode')
    hooks=profile.get('hooks',[])
    if not isinstance(hooks,list) or len(hooks)>128:
        raise TranslationError('invalid native service bindings')
    seen=set()
    for hook in hooks:
        if not isinstance(hook,dict) or hook.get('service')!='load_overlay' or not isinstance(hook.get('cpu'),str) or hook['cpu'] not in processors or hook.get('mode') not in ('arm','thumb'):
            raise TranslationError('unknown native service binding')
        address=_integer(hook.get('address'),'service address')
        cpu=hook['cpu'];key=(cpu,address,hook['mode'])
        alignment=2 if hook['mode']=='thumb' else 4
        if key in seen or address%alignment or not any(m['cpu']==cpu and m['overlay_id'] is None and
                m['address']<=address<m['address']+m['size'] for m in modules):
            raise TranslationError('native service must identify a unique aligned resident address')
        if any(r['cpu']==cpu and r['overlay'] is None and r['address']<=address<r['address']+r['size'] for r in ranges):
            raise TranslationError('native service must be separate from translated instruction ranges')
        seen.add(key)
    observations=profile.get('observe_words',[])
    if not isinstance(observations,list) or len(observations)>256:
        raise TranslationError('invalid observed memory words')
    for address in observations:
        _integer(address,'observed address')
        if address%4 or not _memory(address,4):raise TranslationError('observed word outside supported aligned RAM')
    save=profile.get('save_region',{})
    if not isinstance(save,dict):raise TranslationError('invalid save region')
    save_address=_integer(save.get('address',0),'save address')
    save_size=_integer(save.get('size',0),'save size')
    if save_size and (save_size>1024*1024 or not _memory(save_address,save_size) or
            any(save_address<r['address']+r['size'] and r['address']<save_address+save_size for r in ranges)):
        raise TranslationError('save region must fit supported RAM and cannot contain translated code')
    return dict(modules=modules,ranges=ranges,entries=entries,stacks=stacks,hooks=hooks,
                observations=observations,save_address=save_address,save_size=save_size,instruction_count=instruction_count)


def _write_translation(root, prepared):
    declarations=[]
    for module in prepared['modules']:
        name=module['name'].replace(':','_')
        function='step_'+name
        lines=['#include "runtime.hpp"','namespace nds {',f'bool {function}(Runtime& rt, Cpu& c) {{',
               'switch ((uint64_t(c.pc)<<1) | uint64_t(c.thumb)) {']
        for i in module['instructions']:
            lines.extend([f'case {((i.address<<1)|i.thumb)}ull: {{ // {module["cpu"]} {"Thumb" if i.thumb else "ARM"} {u(i.address)}',
                          f'c.pc = {u(i.address+i.size)}; {i.body} return true;','}'])
        lines.extend(['default:return false;','}','}','}'])
        (root/'game'/f'{name}.cpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        declarations.append(f'bool {function}(Runtime&,Cpu&);')
    lines=['#include "runtime.hpp"','namespace nds {',*declarations]
    for cpu,number in (('arm9',0),('arm7',1)):
        lines.append(f'bool dispatch_{cpu}(Runtime& rt,Cpu& c) {{')
        for m in prepared['modules']:
            if m['cpu']!=cpu:continue
            call='step_'+m['name'].replace(':','_')+'(rt,c)'
            if m['overlay_id'] is None:lines.append(f'if({call})return true;')
            else:lines.append(f'if(rt.active_overlay[{number}]=={m["overlay_id"]} && {call})return true;')
        lines.append('return false; }')
    lines.append('bool service(Runtime& rt,Cpu& c) {')
    for hook in prepared['hooks']:
        number=0 if hook['cpu']=='arm9' else 1
        lines.append(f'if(c.id=={number} && c.pc=={u(hook["address"])} && c.thumb=={str(hook["mode"]=="thumb").lower()}) {{ '
            'rt.load_overlay(c.r[0],c.r[1]);c.r[0]=1;rt.branch(c,c.r[14],true);return true; }')
    lines.extend(['return false; }','}'])
    (root/'game/dispatch.cpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def _write_image(root, prepared, digest):
    lines=['#include "runtime.hpp"','namespace nds {']
    for index,r in enumerate(prepared['ranges']):
        lines.append(f'static const uint8_t expected_{index}[] = {{'+','.join(str(b) for b in r['expected'])+'};')
    lines.append('const CodeRange code_ranges[] = {')
    for index,r in enumerate(prepared['ranges']):
        lines.append('{'+f'{0 if r["cpu"]=="arm9" else 1},{r["overlay"] if r["overlay"] is not None else -1},'
                     f'{u(r["address"])},{r["size"]}u,expected_{index}'+'},')
    lines.extend(['};',f'const unsigned code_range_count = {len(prepared["ranges"])};', 'const Module modules[] = {'])
    layout=[]
    for m in prepared['modules']:
        lines.append('{'+','.join((json.dumps(m['name']),str(0 if m['cpu']=='arm9' else 1),
                    str(m['overlay_id'] if m['overlay_id'] is not None else -1),u(m['address']),str(m['size'])+'u',
                    u(m['bss_address']),str(m['bss_size'])+'u',json.dumps(m['asset'])))+'},')
        layout.append({key:m[key] for key in ('name','cpu','overlay_id','offset','stored_size','size','address',
                                             'bss_address','bss_size','asset','compressed','sha256')})
    lines.extend(['};',f'const unsigned module_count = {len(layout)};'])
    for name in ('entries','stacks'):
        lines.append(f'const uint32_t {name}[2] = {{'+','.join(u(n) for n in prepared[name])+'};')
    lines.extend(['const uint32_t observations[] = {'+','.join(u(n) for n in prepared['observations'] or [0])+'};',
                  f'const unsigned observation_count = {len(prepared["observations"])};',
                  f'const uint32_t save_address = {u(prepared["save_address"])}, save_size = {prepared["save_size"]}u;', '}'])
    (root/'game/image.cpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (root/'game/image.json').write_text(json.dumps(dict(input_sha256=digest,modules=layout),indent=2)+'\n',encoding='utf-8')


def generate(project: dict, root: Path):
    data=project['data'];profile=project['profile'];prepared=prepare(data,profile)
    for folder in ('game','native','tools','cmake','tests'):(root/folder).mkdir()
    digest=hashlib.sha256(data).hexdigest()
    for name in ('runtime.hpp','runtime.cpp','main.cpp'):
        (root/'native'/name).write_text(_source(name),encoding='utf-8')
    for folder in ('native','tools'):
        (root/folder/'LICENSE').write_text(_source('runtime.LICENSE'),encoding='utf-8')
    _write_translation(root,prepared);_write_image(root,prepared,digest)
    extractor=f'MAX_MODULE_SIZE = {MAX_MODULE_SIZE}\n\n'+inspect.getsource(decompress_blz)+'\n'+_source('extract.py')
    (root/'tools/extract_assets.py').write_text(extractor,encoding='utf-8')
    (root/'reviewed-profile.json').write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(DSStatic LANGUAGES CXX)\n'
        'set(CMAKE_CXX_STANDARD 17)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\n'
        'include(cmake/Runtime.cmake)\nfile(GLOB GAME_SOURCES CONFIGURE_DEPENDS game/*.cpp)\n'
        'add_executable(ds_static ${GAME_SOURCES} native/main.cpp)\n'
        'target_link_libraries(ds_static PRIVATE ds_runtime)\n'
        'enable_testing()\nadd_test(NAME original_program COMMAND ds_static --assets "${CMAKE_CURRENT_SOURCE_DIR}/assets")\n',encoding='utf-8')
    (root/'cmake/Runtime.cmake').write_text('add_library(ds_runtime STATIC native/runtime.cpp)\n'
        'target_include_directories(ds_runtime PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/native")\n',encoding='utf-8')
    (root/'tests/README.md').write_text('`ctest --test-dir build -C Release --output-on-failure` executes the translated program.\n'
        'Successful termination is an execution check, not retail gameplay qualification.\n',encoding='utf-8')
    (root/'.gitignore').write_text('/assets/\n/build/\n/originals/\n/saves/\n*.nds\n',encoding='utf-8')
    (root/'README.md').write_text('''# Experimental DS static PC repository

This source repository contains C++ translated from the reviewed ARM9/ARM7 code
ranges, a small native memory/dispatch runtime and standalone asset extraction.
It is an early execution backend, not a qualified retail DS port. Graphics,
audio, interrupts, accurate CPU timing, most device registers and full instruction
coverage remain unimplemented. Unknown execution targets/devices, code writes,
unaligned accesses and unsupported instructions fail explicitly. There is no
interpreter, runtime compiler, DS emulator process or BIOS dependency.

Prerequisites: [Python 3.9+](https://www.python.org/downloads/),
[CMake 3.20+](https://cmake.org/download/) and a C++17 compiler
([Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
with Desktop development with C++ on Windows, or your distribution's GCC/Clang on Linux).
No decomp.wtf installation or console compiler is needed to build this output.

```sh
python tools/extract_assets.py /path/to/original.nds
cmake -S . -B build
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Run `build/ds_static --assets assets` on Linux or
`build/Release/ds_static.exe --assets assets` with Visual Studio. Output reports
the guest registers, reviewed memory words and overlay loads as JSON. The
instruction budget is bounded (`--max-steps N`). An optional `--save saves/game.sav`
persists the profile's reviewed RAM range; create its parent directory first.
This RAM checkpoint is not yet DS cartridge save-device emulation.

`game/` contains the translated program and module layout. `native/` contains
the runtime; `reviewed-profile.json` records exact code modes, native service
bindings, input identity and observations. The load_overlay binding replaces an
explicitly identified loader entry, loading reviewed modules and clearing BSS.
One overlay is currently active per CPU. Constructor execution is not implemented.
Execution starts at both ROM header entries with the reviewed stacks, clear
NZCV flags and a host harness return sentinel in LR. Scheduling alternates one
instruction per active CPU; it does not reproduce DS hardware cycle timing.

Assets are extracted from the exact input SHA-256 and excluded from Git. Code
bytes in module assets must still agree with the static translation. Generated
game source is private code derived from the owner's input. Keep it private.
`pc-project.json` records generated-file integrity; it does not certify gameplay.
''',encoding='utf-8')
    backend_revision=revision()
    manifest=dict(schema=pc.SCHEMA,platform='nds',backend=dict(id=BACKEND_ID,revision=backend_revision),
        runtime=dict(id='nds-original-static-runtime',revision=backend_revision),execution_model='static-recompiled',
        inputs=[dict(sha256=digest)],build=dict(system='cmake',target='ds_static'),
        fallback=dict(interpreter=False,runtime_compilation=False),
        qualification=dict(experimental=True,retail=False,graphics=False,audio=False,cycle_accurate=False,
                           instruction_count=prepared['instruction_count']),
        native_bindings=prepared['hooks'],files={})
    for file in sorted(root.rglob('*')):
        if file.is_file():manifest['files'][file.relative_to(root).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    (root/'pc-project.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def export(rom: Path, profile_path: Path, output: Path):
    rom,profile_path=Path(rom),Path(profile_path)
    if rom.stat().st_size>512*1024*1024 or profile_path.stat().st_size>1024*1024:
        raise TranslationError('ROM or reviewed profile exceeds supported bounds')
    data=rom.read_bytes();profile=json.loads(profile_path.read_text(encoding='utf-8'))
    prepare(data,profile)  # reject unsupported input before creating an output directory
    adapter=pc.Backend(BACKEND_ID,'nds',revision(),generate)
    return pc.export_backend(dict(platform='nds',root=str(rom.parent),data=data,profile=profile),output,adapter)
