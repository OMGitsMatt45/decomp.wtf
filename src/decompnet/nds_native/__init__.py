"""Generate DS static C++ projects with a pinned, source-shipped hardware runtime.

This remains an explicitly experimental adapter until retail compatibility is
qualified. The original small nds_pc backend remains useful for CPU comparison.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
from importlib import resources
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from contextvars import ContextVar

import yaml

from .. import pc, toolchains
from ..rom.nds_modules import NdsImage

BACKEND_ID = 'nds-dsr-experimental'
SDK_COMMIT = 'b8fc609c20699ad5afe36922b7f2aa42436ec931'
PROFILE_SCHEMA = 'decomp.wtf.nds-static-profile/v1'
_progress = ContextVar('nds_native_progress', default=None)


def _log(message):
    callback = _progress.get()
    if callback is None:print(message,file=sys.stderr)
    else:callback(message)


def _source(name):
    return resources.files(__package__).joinpath(name).read_text(encoding='utf-8')


def revision():
    digest = hashlib.sha256(SDK_COMMIT.encode())
    for name in ('__init__.py','main.cpp','video.cpp','video.hpp','hash.hpp','save_lock.hpp','audio_queue.hpp','cheats.hpp','settings.hpp','Runtime.cmake','extract.py','emitter_patch.py','wider_table.py','io_patch.py','abi_patch.py','callbacks.py','geometry_patch.py','capture_patch.py','capture_origin.h','foreground_patch.py','obj_capture_patch.py','scene_effects_patch.py','projection_patch.py','geometry_capacity_patch.py','guest_work_patch.py'):
        digest.update(name.encode()+b'\0'+_source(name).encode())
    return digest.hexdigest()


def _sdk():
    try:
        root = toolchains.ensure('dsr-sdk',log=_log)
    except toolchains.ToolchainError as error:
        raise pc.PCError(str(error)) from error
    name = 'decompnet._nds_dsr_recomp'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name,root/'recomp/__init__.py',
                submodule_search_locations=[str(root/'recomp')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    emitter=importlib.import_module(name+'.emitter')
    from .emitter_patch import install
    install(emitter)
    return root, emitter, importlib.import_module(name+'.dsd_manifest')


def _tool(root, name):
    key = 'decompnet._nds_dsr_'+name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key,root/'tools'/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def _run(command, cwd, what):
    _log(what+'...')
    try:
        result = subprocess.run(list(map(str,command)),cwd=cwd,capture_output=True,text=True,
                                encoding='utf-8',errors='replace',timeout=3500)
    except subprocess.TimeoutExpired as error:
        raise pc.PCError(what+' timed out') from error
    if result.returncode:
        raise pc.PCError(what+' failed:\n'+(result.stdout+result.stderr)[-4000:])


def _analyze(rom, work, sdk, reader, input_format, bios):
    """Use the existing qualified DS decoder, without installing a matching compiler."""
    from ..forks.ds_template.tools.nds_input import finish_layout
    try:
        dsd = toolchains.ensure('dsd',log=_log)
        dsd = toolchains.binary('dsd')
    except toolchains.ToolchainError as error:
        raise pc.PCError(str(error)) from error
    template = resources.files('decompnet.forks').joinpath('ds_template/tools')
    tools = work/'tools';tools.mkdir()
    for name in ('extract.py','nds_input.py'):
        (tools/name).write_text(template.joinpath(name).read_text(encoding='utf-8'),encoding='utf-8')
    extracted = work/'extract'
    command=[sys.executable,tools/'extract.py',dsd,'rom','extract','--rom',rom,
             '--output-path',extracted,'--analysis-layout','--input-format',input_format]
    if bios:
        if input_format=='decrypted':raise pc.PCError('decrypted input must not be decrypted again with a BIOS')
        command.extend(['--arm7-bios',bios])
    _run(command,work,'DS module extraction')
    config_dir=work/'config';build=work/'build'
    init=[dsd,'init','--rom-config',extracted/'config.yaml','--output-path',config_dir,'--build-path',build]
    try:
        _run(init,work,'DS code analysis')
    except pc.PCError as error:
        if 'leads to no function' not in str(error):raise
        if config_dir.exists():shutil.rmtree(config_dir)
        _run([*init,'--allow-unknown-function-calls'],work,'DS code analysis')
    config=config_dir/'arm9/config.yaml'
    finish_layout(config)
    document=yaml.safe_load(config.read_text(encoding='utf-8'))
    images=(config.parent/document['build_path']/'build').resolve();images.mkdir(parents=True,exist_ok=True)
    for name in ('arm9','itcm','dtcm'):
        shutil.copyfile(extracted/'arm9'/(name+'.yaml'),images/(name+'.yaml'))
        binary=images/(name+'.bin')
        if not binary.exists():shutil.copyfile(extracted/'arm9'/(name+'.bin'),binary)
    shutil.copyfile(extracted/'arm9_overlays/overlays.yaml',images/'arm9_overlays.yaml')
    for path in (extracted/'arm9_overlays').glob('ov*.bin'):
        binary=images/('arm9_'+path.name)
        if not binary.exists():shutil.copyfile(path,binary)
    arm9=reader.build_arm9_manifest(config)
    metadata=yaml.safe_load((extracted/'arm7/arm7.yaml').read_text(encoding='utf-8'))
    analyzer=_tool(sdk,'arm7_analyze')
    from .callbacks import complete
    recovered=complete(arm9,_sdk()[1],reader)
    if recovered['callbacks']:_log(f"Recovered {len(recovered['callbacks'])} referenced ARM9 callbacks and callees")
    if recovered['gaps']:_log(f"Recovered {len(recovered['gaps'])} additional ARM9 code-gap functions")
    path=extracted/'arm7/arm7.bin'
    result=analyzer.analyze_image(path.read_bytes(),base=metadata['base_address'],
        entry=metadata['entry_function'],callback=metadata['autoload_callback'],image_path=path)
    arm7_path,_=analyzer.write_outputs(result,work/'arm7-analysis')
    arm7=json.loads(arm7_path.read_text(encoding='utf-8'))
    derive=_tool(sdk,'derive_abi_config')
    from .abi_patch import install
    install(derive)
    abi={}
    for manifest in (arm9,arm7):
        path=work/(manifest['cpu']+'.manifest.json')
        path.write_text(json.dumps(manifest),encoding='utf-8')
        try:
            values,unresolved=derive.derive(derive.load_functions(path,work))
        except ValueError as error:
            raise pc.PCError(manifest['cpu']+' native thread ABI could not be established: '+str(error)) from error
        if unresolved:raise pc.PCError(manifest['cpu']+' has unresolved native thread ABI fields')
        abi[manifest['cpu']]=values
    # Secure-area decoding is performed once at import. Ship a private patch
    # derived from this owner's input, so the output needs no BIOS/toolkit.
    with rom.open('rb') as stream:
        stream.seek(0x20);offset=struct.unpack('<I',stream.read(4))[0]
    prefix=(extracted/'arm9/arm9.bin').read_bytes()[:0x800]
    with rom.open('rb') as stream:
        stream.seek(offset);stored=stream.read(len(prefix))
    patches=[]
    if offset>=0x4000 and prefix!=stored:
        patches.append(dict(offset=offset,hex=prefix.hex()))
    return [arm9,arm7],dict(abi=abi,asset_patches=patches)


def _reviewed(data, profile, work):
    if not isinstance(profile,dict) or profile.get('schema')!=PROFILE_SCHEMA:
        raise pc.PCError('unsupported reviewed DS profile')
    if profile.get('input_sha256')!=hashlib.sha256(data).hexdigest():
        raise pc.PCError('reviewed profile ROM SHA-256 differs from input')
    if profile.get('hooks'):
        raise pc.PCError('hardware runtime requires the original loader code; remove native test-harness hooks')
    if profile.get('save_region'):
        raise pc.PCError('RAM checkpoints belong to nds-generate; nds-native uses the cartridge save device')
    image=NdsImage(data)
    if image.modules['arm9'].offset>=0x4000:
        raise pc.PCError('retail DS input requires automatic module decoding, without --profile')
    code=profile.get('code')
    if not isinstance(code,dict) or not code or set(code)-set(image.modules):
        raise pc.PCError('reviewed code must identify known DS modules')
    manifests=[dict(cpu=cpu,arch=arch,modules=[]) for cpu,arch in (('arm9','v5te'),('arm7','v4t'))]
    resident_ids={'arm9':-1,'arm7':-4}
    next_id={'arm9':-100,'arm7':-5}
    for name, ranges in code.items():
        module=image.modules[name]
        raw=data[module.offset:module.offset+module.stored_size] if name=='arm9' else image.code(name)
        if not isinstance(ranges,list):raise pc.PCError('reviewed code ranges must be a list')
        functions=[];occupied=[]
        for entry in ranges:
            if not isinstance(entry,dict):raise pc.PCError('invalid reviewed code range')
            address,size,mode=entry.get('address'),entry.get('size'),entry.get('mode')
            if type(address) is not int or type(size) is not int or mode not in ('arm','thumb'):
                raise pc.PCError('invalid reviewed code address, size or mode')
            alignment=2 if mode=='thumb' else 4
            if address%alignment or size<=0 or size%alignment or not module.address<=address<address+size<=module.address+len(raw):
                raise pc.PCError('reviewed code range is unaligned or outside its module')
            if any(address<end and begin<address+size for begin,end in occupied):
                raise pc.PCError('overlapping reviewed code ranges')
            occupied.append((address,address+size))
            functions.append(dict(addr=address,size=size,thumb=mode=='thumb',name=f'guest_{address:08x}'))
        path=work/(name.replace(':','_')+'.bin');path.write_bytes(raw)
        if module.overlay_id is not None:
            module_id=module.overlay_id
            if module_id>0x7fffffff:raise pc.PCError('overlay ID exceeds the native runtime range')
        elif name in resident_ids:
            module_id=resident_ids[name]
        else:
            module_id=next_id[module.cpu];next_id[module.cpu]-=1
        manifests[0 if module.cpu=='arm9' else 1]['modules'].append(dict(name=name,module_id=module_id,
            base=module.address,image=str(path.resolve()),functions=functions))
    for index, header in enumerate((0x24,0x34)):
        entry=struct.unpack_from('<I',data,header)[0]
        if not any(fn['addr']==entry&~1 and fn['thumb']==bool(entry&1)
                for module in manifests[index]['modules'] for fn in module['functions']):
            raise pc.PCError('both DS header entries need a reviewed translation with the right instruction mode')
    processors=profile.get('processors')
    if not isinstance(processors,dict) or set(processors)!={'arm9','arm7'}:
        raise pc.PCError('reviewed profile must identify both processor stacks')
    for cpu in ('arm9','arm7'):
        item=processors[cpu]
        sp=item.get('stack') if isinstance(item,dict) else None
        private=(0x00800004,0x00804000) if cpu=='arm9' else (0x03800004,0x03810000)
        if type(sp) is not int or sp%4 or not (0x02000004<=sp<=0x02400000 or private[0]<=sp<=private[1]):
            raise pc.PCError(cpu+' reviewed stack is not aligned RAM accessible to that processor')
    observations=profile.get('observe_words',[])
    if not isinstance(observations,list) or len(observations)>256 or any(type(a) is not int or a%4 or
            not (0x02000000<=a<0x02400000) for a in observations):
        raise pc.PCError('observations must identify aligned main RAM words')
    return manifests,dict(processors=processors,observe_words=observations)


def _runtime(sdk, root):
    target=root/'native/dsr'
    target.mkdir()
    shutil.copytree(sdk/'runtime',target/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('LICENSE','NOTICE','LEGAL.md'):
        shutil.copyfile(sdk/name,target/name)
    shutil.copytree(sdk/'third_party',target/'third_party')
    from .io_patch import patch
    patch(target)
    from .geometry_patch import patch as patch_geometry
    patch_geometry(target)
    from .projection_patch import patch as patch_projection
    patch_projection(target)
    from .capture_patch import patch as patch_capture
    patch_capture(target)
    from .foreground_patch import patch as patch_foreground
    patch_foreground(target)
    from .obj_capture_patch import patch as patch_obj_capture
    patch_obj_capture(target)
    from .scene_effects_patch import patch as patch_scene_effects
    patch_scene_effects(target)
    from .geometry_capacity_patch import patch as patch_geometry_capacity
    patch_geometry_capacity(target)
    from .guest_work_patch import patch as patch_guest_work
    patch_guest_work(target)
    # Upstream copies both header programs through the ARM9 bus. ARM7 IWRAM
    # is private, so booting a program there otherwise leaves its literals zero.
    path=target/'runtime/core/src/machine.cpp'
    text=path.read_text(encoding='utf-8')
    changes={
        'auto copy_rom = [this](std::uint32_t source, std::uint32_t destination, std::uint32_t size)':
        'auto copy_rom = [this](CpuId cpu, std::uint32_t source, std::uint32_t destination, std::uint32_t size)',
        'write(CpuId::Arm9, destination + i, buffer[i], 8);':'write(cpu, destination + i, buffer[i], 8);',
        'copy_rom(arm9_offset, arm9_dest, arm9_size);':'copy_rom(CpuId::Arm9, arm9_offset, arm9_dest, arm9_size);',
        'copy_rom(arm7_offset, arm7_dest, arm7_size);':'copy_rom(CpuId::Arm7, arm7_offset, arm7_dest, arm7_size);',
    }
    for before,after in changes.items():
        if text.count(before)!=1:raise pc.PCError('pinned DS runtime boot patch no longer matches source')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
    path=target/'runtime/core/src/bus.cpp'
    text=path.read_text(encoding='utf-8')
    itcm='rt.cp15_control & (1u << 16)'
    dtcm='rt.cp15_control & (1u << 18)'
    if text.count(itcm)!=3 or text.count(dtcm)!=3:
        raise pc.PCError('pinned DS runtime TCM patch no longer matches source')
    # ARM946 CP15 control: DTCM enable is bit 16, ITCM enable is bit 18.
    text=text.replace(itcm,'__DECOMP_ITCM_ENABLE__').replace(dtcm,itcm).replace('__DECOMP_ITCM_ENABLE__',dtcm)
    path.write_text(text,encoding='utf-8')
    path=target/'runtime/core/src/timing.cpp'
    text=path.read_text(encoding='utf-8')
    before='''            trigger_one_dma(cpu_index, channel);
        }
    }
}

void Machine::Impl::enable_dma'''
    after='''            // READY is held for the current card block by this runtime.
            // A repeating one-word DMA must therefore service successive
            // requests here, stopping at block completion or DMA disable.
            for (unsigned request = 0; request < 8192; ++request) {
                trigger_one_dma(cpu_index, channel);
                if (mode != 5 || !card || dma.latched_count != 1 ||
                    (dma.control & 0x8200u) != 0x8200u ||
                    dma.current_src != 0x04100010u ||
                    (card->io_read(0x040001a4u, 32) & 0x80800000u) != 0x80800000u)
                    break;
            }
        }
    }
}

void Machine::Impl::enable_dma'''
    if text.count(before)!=1:raise pc.PCError('pinned DS runtime card DMA patch no longer matches source')
    path.write_text(text.replace(before,after),encoding='utf-8')
    path=target/'runtime/core/src/runtime.cpp'
    text=path.read_text(encoding='utf-8')
    before=r'''                 "[dsr] hint: the program reached code its generated tables do not contain. This usually means the image "
                 "differs from the one tools/build_port.py was run on (another region or revision, or a modified file); "
                 "rebuild with that exact file: python tools/build_port.py --rebuild-workspace --rom <your .nds>.\n");'''
    after=r'''                 "[dsr] Static execution reached an unresolved target. Keep pc-project.json and "
                 "these diagnostics for review of translation coverage and runtime behavior.\n");'''
    if text.count(before)!=1:raise pc.PCError('pinned DS runtime diagnostic patch no longer matches source')
    text=text.replace(before,after)
    before=r'''    std::fprintf(stderr,
                 "[dsr] add a function entry with --extra-entries: func_%08x kind:function(arm,size=0x4) addr:0x%08x\n",
                 target & ~1u, target & ~1u);
'''
    if text.count(before)!=1:raise pc.PCError('pinned DS runtime entry hint patch no longer matches source')
    path.write_text(text.replace(before,''),encoding='utf-8')
    (target/'DECOMP_WTF_PATCHES.md').write_text('''# decomp.wtf runtime changes

Captured-scene provenance and native foreground metadata follow bitmap OBJ
through VRAM mappings, transforms and compositing, as well as background layers.
Optional pre-master scene foreground and scanline-routed brightness records let
customized presentations apply LCD fades after world/UI composition.

Optional captured-3D origins retain generation and source coordinates through\nVRAM captures and direct bitmaps. CPU/DMA writes invalidate touched texels;\nblended/brightness/overlapping mappings remain native. Tracking is opt-in and\nchanges no emulated colours or registers.\nBase: 0bAndyWirus/DQ9-Decomp b8fc609c20699ad5afe36922b7f2aa42436ec931 (MIT).
ARM9 DMA fill latches have explicit byte/halfword/word storage handling, including
fixed-source DMA reads. ARM7 RCNT retains its 16-bit GPIO control value without
writing the adjacent read-only extended key input. These accesses no longer
produce unsupported-I/O diagnostics; external serial link behavior is separate.
The ARM7 wireless RAM window has independent 8 KiB storage and its address
mirror, respecting the existing power gate. Wireless MAC/network services remain
unsupported and retain their diagnostics.
The direct boot copy uses each destination processor's bus. In the base source,
ARM7 private WRAM receives no initialized bytes when copied through ARM9.
Our original dual-CPU fixture covers this layout and its live literal loads.
The ARM946 CP15 TCM enables use bit 16 for DTCM and bit 18 for ITCM, in both
fast page mappings and slow bus accesses. The base source interchanges them;
an original fixture exercises DTCM with ITCM independently disabled.
Card DMA services repeated one-word transfers while READY is held for the same
block. It stops when the block ends, the DMA disables, or its source changes;
the bounded loop cannot consume another card block. An original guest fixture
reads all 128 words of one block using repeating one-word DMA and checks data
and the cartridge completion IRQ. The latched count, rather than a later
programmed count write, limits this correction to one-word transfers. Other
DMA block sizes retain the pinned runtime's notification/rearm behavior.
Unresolved-target diagnostics refer to this generated repository and retain
CPU/register details. They no longer suggest a missing upstream build command
or a guessed ARM function entry, which could conceal a translation defect.
Geometry assembly rejects fully clipped and culled polygons before allocating
finite geometry RAM. Rolling input slots preserve triangle/quad strip endpoints
and share accepted vertices. The base source charges every submitted vertex
and polygon, including off-screen scenery, which can discard later characters.
Visible geometry retains the original buffer limits and overflow diagnostics;
partial polygons retain the existing rasterizer's clipping arithmetic.
''',encoding='utf-8')


def _profile(root, digest, reviewed, save_type, renderer):
    observations=reviewed.get('observe_words',[])
    lines=['#pragma once','#include "hash.hpp"','#include <dsr/machine.h>','namespace profile {',
           'inline constexpr const char* asset_sha256='+json.dumps(digest)+';',
           'inline constexpr const char* save_type='+json.dumps(save_type)+';',
           'inline constexpr const char* renderer='+json.dumps(renderer)+';',
           'inline constexpr uint32_t observations[]={'+','.join(hex(a)+'u' for a in observations or [0])+'};',
           f'inline constexpr unsigned observation_count={len(observations)};',
           'inline void verify_input(const std::filesystem::path& path) {',
           'if(input_sha256(path)!='+json.dumps(digest)+')throw std::runtime_error("DS assets SHA-256 differs from translated input");','}',
           'inline void configure(dsr::MachineConfig& config) {']
    for cpu in ('arm9','arm7'):
        if cpu not in reviewed.get('abi',{}):continue
        lines.append('{ dsr::ThreadAbi value;')
        for name,value in reviewed['abi'][cpu].items():
            lines.append(f'value.{name}={value};')
        lines.extend([f'config.guest_abi.{cpu}=value;','}'])
    lines.extend(['}','inline void initialize(dsr::Machine& machine) {'])
    for cpu,enum in (('arm9','Arm9'),('arm7','Arm7')):
        if cpu in reviewed.get('processors',{}):
            lines.append(f'machine.cpu(dsr::CpuId::{enum}).r[13]={reviewed["processors"][cpu]["stack"]}u;')
    lines.extend(['}','}'])
    (root/'native/profile.hpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def generate(project,root):
    sdk,emitter,reader=_sdk()
    rom=Path(project['rom']);data=rom.read_bytes();digest=hashlib.sha256(data).hexdigest()
    for directory in ('game','native','tools','cmake','tests'):(root/directory).mkdir()
    _runtime(sdk,root)
    stats=[]
    with tempfile.TemporaryDirectory(prefix='.ds-analysis-',dir=root) as temporary:
        work=Path(temporary)
        if project.get('profile') is not None:
            manifests,reviewed=_reviewed(data,project['profile'],work)
        else:
            manifests,reviewed=_analyze(rom,work,sdk,reader,project['input_format'],project.get('bios'))
        for manifest in manifests:
            output=root/'game'/manifest['cpu']
            result=emitter.emit_manifest(manifest,output,chunk_size=100)
            if result['undefined_sites']:
                raise pc.PCError(f'{manifest["cpu"]} has {result["undefined_sites"]} unsupported instruction sites: '+
                    json.dumps(result['unsupported_sites'][:3]))
            stats.append(dict(cpu=manifest['cpu'],functions=result['functions'],blocks=result['blocks'],undefined_sites=result['undefined_sites']))
        facts=[]
        for manifest in manifests:
            for module in manifest['modules']:
                raw=Path(module['image']).read_bytes()
                facts.append({**{k:v for k,v in module.items() if k!='image'},'cpu':manifest['cpu'],
                              'decoded_sha256':hashlib.sha256(raw).hexdigest()})
        (root/'game/recovery.json').write_text(json.dumps(facts,indent=2)+'\n',encoding='utf-8')
    patches=reviewed.get('asset_patches',[])
    asset_digest=digest
    if patches:
        normalized=bytearray(data)
        for patch in patches:
            value=bytes.fromhex(patch['hex']);start=patch['offset']
            if not 0<=start<start+len(value)<=len(data):raise pc.PCError('decoded asset patch exceeds the original ROM')
            normalized[start:start+len(value)]=value
        asset_digest=hashlib.sha256(normalized).hexdigest()
    _profile(root,asset_digest,reviewed,project['save_type'],project['renderer'])
    (root/'game/input.json').write_text(json.dumps(dict(sha256=digest,size=len(data),
        asset_sha256=asset_digest,asset_patches=patches),indent=2)+'\n',encoding='utf-8')
    for source,destination in (('main.cpp','native/main.cpp'),('hash.hpp','native/hash.hpp'),
                               ('save_lock.hpp','native/save_lock.hpp'),
                               ('audio_queue.hpp','native/audio_queue.hpp'),
                               ('cheats.hpp','native/cheats.hpp'),('settings.hpp','native/settings.hpp'),
                               ('video.cpp','native/video.cpp'),('video.hpp','native/video.hpp'),
                               ('Runtime.cmake','cmake/Runtime.cmake'),('extract.py','tools/extract_assets.py')):
        (root/destination).write_text(_source(source),encoding='utf-8')
    license=resources.files('decompnet.nds_pc').joinpath('runtime.LICENSE').read_text(encoding='utf-8')
    for folder in ('native','tools'):(root/folder/'LICENSE').write_text(license,encoding='utf-8')
    (root/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(DSNative LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()
file(GLOB GAME_SOURCES CONFIGURE_DEPENDS game/arm9/*.cpp game/arm7/*.cpp)
add_executable(ds_pc ${GAME_SOURCES} native/main.cpp)
target_include_directories(ds_pc PRIVATE native game/arm9 game/arm7)
if(MSVC)
  target_compile_options(ds_pc PRIVATE /bigobj /O2)
else()
  target_compile_options(ds_pc PRIVATE -O2 -fno-strict-aliasing)
endif()
include(cmake/Runtime.cmake)
target_link_libraries(ds_pc PRIVATE ds_runtime)
enable_testing()
add_test(NAME native_boot COMMAND ds_pc --assets "${CMAKE_CURRENT_SOURCE_DIR}/assets"
  --save "${CMAKE_CURRENT_BINARY_DIR}/test.sav" --headless --frames 2)
set_tests_properties(native_boot PROPERTIES TIMEOUT 30)
''',encoding='utf-8')
    (root/'.gitignore').write_text('/assets/\n/build/\n/saves/\n/captures/\n*.nds\n',encoding='utf-8')
    # Manifest hashes cover exact bytes. Git for Windows must not rewrite them.
    (root/'.gitattributes').write_text('* -text\n',encoding='utf-8')
    (root/'README.md').write_text('''# Experimental DS PC source project

Generated ARM9/ARM7 C++ in `game/` runs with a pinned MIT DS runtime, whose
source, license and attribution are included in `native/dsr/`. It supplies
DS memory, interrupts/timing, graphics, audio, input and cartridge services.
This is static recompilation: no instruction interpreter, JIT or emulator
process is an execution fallback. Compatibility still requires title validation.

Only your original DS ROM is needed for assets. BIOS, firmware and mobile OBB
files are not required. Sound comes from the DS game. Do not publish generated
game sources or original assets without the relevant rights.

Install [Python 3.9+](https://www.python.org/downloads/),
[CMake 3.20+](https://cmake.org/download/) and a C++20 compiler
([Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022),
Desktop development with C++, on Windows; GCC/Clang on Linux).
SDL2 2.32.10 is downloaded and checksum-verified by CMake automatically.
The DS runtime source is already included. No decomp.wtf or console compiler
installation is needed to build this repository.

Linux desktop builds also need X11/Xext and OpenGL/EGL development libraries
before CMake configures SDL. On Ubuntu/Debian:

```sh
sudo apt-get install build-essential libx11-dev libxext-dev libgl-dev libegl-dev
```

Other distributions need equivalent development packages. See
[SDL's Linux build documentation](https://wiki.libsdl.org/SDL2/Installation#linuxunix).
Headless builds do not need these graphics packages.

```sh
python tools/extract_assets.py /path/to/original.nds
cmake -S . -B build
cmake --build build --config Release --parallel 2
ctest --test-dir build -C Release --output-on-failure
```

Run `build/ds_pc --assets assets` on Linux or
`build/Release/ds_pc.exe --assets assets` with Visual Studio.
Arrow keys move; X/Z are A/B; S/A are X/Y; Q/W are L/R;
F1 opens Game settings, including the ROM-bound data-cheat menu. Cheats start
disabled each launch. Game projects can supply `cheats.txt` beside `assets`.
Enter/Backspace are Start/Select. Click the lower screen for touch; Escape quits.
F11 switches fullscreen at the current monitor's native resolution. The initial
window size comes from the active monitor's usable area. Resizing or moving
between monitors updates rendering to the actual drawable size, including
high-DPI scaling. `--resolution WIDTHxHEIGHT` optionally sets an initial window
size; the renderer keeps adapting after that.

## Rendering

The export's renderer choice is recorded in `native/profile.hpp`
and the manifest. They can be changed without regenerating game code:

```sh
./build/ds_pc --renderer opengl --fullscreen
```

`--renderer auto` tries OpenGL 3.3, reporting a software fallback if unavailable.
`opengl` requires the driver/context; it draws transformed game geometry at the
drawable resolution. `software` preserves the DS-resolution picture. OpenGL
loads through SDL. Driver downloads: [NVIDIA](https://www.nvidia.com/Download/index.aspx),
[AMD](https://www.amd.com/en/support),
[Intel](https://www.intel.com/content/www/us/en/download-center/home.html), or
your Linux distribution's graphics packages.
The native DS renderer stays active for display capture, UI and guarded effects.

Both original LCDs remain visible and preserve their aspect ratios. Touch
coordinates follow the displayed lower LCD. Original text/sprites remain sharply
scaled. Fog, edge marking, shadow/depth-equal polygons and clear-image mode
currently use the native path. Game-specific camera, menu and culling
enhancements can be added to this source project later. Mobile sound, party chat
and other title-specific extras are outside this generic DS output.

`--capture DIR` also saves `display.ppm` at the presented drawable resolution.
The JSON result identifies the actual renderer, driver, dimensions and
geometry draw count. Headless mode runs the DS machine without
a presentation driver.

Cartridge saves are written to `saves/game.sav`, or the path given by `--save`.
The selected save chip is pinned in `native/profile.hpp`; review it for each game.
`auto` infers from an existing raw save. Choose the actual chip for a new game.

The RTC uses your computer's current local date/time, including after restarting.
For repeatable tests, `--rtc-start 1704067200` starts at 2024-01-01 00:00:00 UTC
and advances with emulated time. Unix timestamps must fall in 2000..2099 UTC.
JSON records `rtc.mode` (`local` or `fixed-utc`) and `rtc.start_unix` (null for local).

For a bounded headless check use `--headless --frames 300`. Add `--capture DIR`
for final PPM screens, `--audio-pcm FILE` for little-endian signed stereo samples,
or `--input-script FILE` for rows `frame button_mask touch_x touch_y` (use -1 -1
for no touch). JSON reports frame/tick totals, screen hashes, observations and
unimplemented I/O count. A headless-only build uses `-DNDS_WITH_SDL=OFF`.
For private diagnostics, `--dump-memory DIR` also saves graphics registers,
OAM, palettes, physical VRAM banks and the last activated geometry beside the
main/ARM7/DTCM RAM images. These are end-of-frame snapshots, not per-line history.

The manifest records exact input, generated-file hashes, backend/runtime source
revisions and static execution. It does not certify that gameplay is complete.
The runtime uses approximated CPU timing and a partial hardware model. A clean
build and successful boot are separate from field/battle/save compatibility.
''',encoding='utf-8')
    manifest=dict(schema=pc.SCHEMA,platform='nds',backend=dict(id=BACKEND_ID,revision=revision()),
        runtime=dict(id='dq9-decomp-dsr',revision=SDK_COMMIT),inputs=[dict(sha256=digest)],
        execution_model='static-recompiled',build=dict(system='cmake',target='ds_pc'),
        fallback=dict(interpreter=False,runtime_compilation=False),qualification=dict(experimental=True,retail=False),
        code_generation=stats,save_type=project['save_type'],asset_sha256=asset_digest,
        presentation=pc.presentation(project['renderer'],screens=2,screen_mode=project['screen_mode']),files={})
    for path in sorted(root.rglob('*')):
        if path.is_file():manifest['files'][path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'pc-project.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def _prepare(rom,*,profile=None,input_format='auto',arm7_bios=None,save_type='auto',renderer='auto',screen_mode='dual'):
    rom=Path(rom).resolve()
    if not rom.is_file() or not 0x200<=rom.stat().st_size<=512*1024*1024:
        raise pc.PCError('DS input must be an existing ROM no larger than 512 MiB')
    NdsImage(rom.read_bytes())  # reject invalid headers/TWL before any dependency install
    if input_format not in ('auto','decrypted'):raise pc.PCError('input format must be auto or decrypted')
    if renderer not in ('auto','opengl','software'):raise pc.PCError('renderer must be auto, opengl or software')
    if screen_mode != 'dual':raise pc.PCError('screen mode must be dual; combined screens are a game-specific customization')
    bios=None
    if arm7_bios is not None:
        if input_format=='decrypted':raise pc.PCError('decrypted input must not be decrypted again with a BIOS')
        bios=Path(arm7_bios).expanduser().resolve()
        if not bios.is_file() or bios.stat().st_size!=16*1024:
            raise pc.PCError('ARM7 BIOS must be an existing 16 KiB file')
    if save_type not in ('auto','eeprom512b','eeprom8k','eeprom64k','eeprom128k','flash256k','flash512k','flash1m','flash8m'):
        raise pc.PCError('unsupported cartridge save type')
    reviewed=None
    if profile is not None:
        path=Path(profile)
        if path.stat().st_size>1024*1024:raise pc.PCError('reviewed profile is too large')
        reviewed=json.loads(path.read_text(encoding='utf-8'))
    return dict(platform='nds',root=str(rom.parent),rom=str(rom),profile=reviewed,
        input_format=input_format,bios=bios,save_type=save_type,renderer=renderer,screen_mode=screen_mode)


def _generate_project(project,root):
    prepared=_prepare(project['rom'],input_format=project.get('input_format','auto'),
                      arm7_bios=project.get('bios'),save_type=project.get('save_type','auto'),
                      renderer=project.get('renderer','auto'),screen_mode=project.get('screen_mode','dual'))
    generate(prepared,root)


def backend():
    return pc.Backend(BACKEND_ID,'nds',revision(),_generate_project,experimental=True)


def export(rom,output,*,profile=None,input_format='auto',arm7_bios=None,save_type='auto',renderer='auto',screen_mode='dual',log=None):
    project=_prepare(rom,profile=profile,input_format=input_format,arm7_bios=arm7_bios,save_type=save_type,
                     renderer=renderer,screen_mode=screen_mode)
    token=_progress.set(log)
    try:
        return pc.export_backend(project,Path(output),pc.Backend(BACKEND_ID,'nds',revision(),generate,True))
    finally:
        _progress.reset(token)
