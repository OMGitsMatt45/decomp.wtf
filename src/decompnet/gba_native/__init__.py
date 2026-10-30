"""Standalone GBA native players with GPU rendering and a separate reference probe."""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from .. import pc, toolchains
from ..rom.gba import is_gba, read_info

SDK_COMMIT = 'a3eb412f79627eaae27e2523039d893f72dada1d'
SDK_TREE_SHA256 = '521b2093b9eb66bffb501484bf187df34b83e87fcb0f56e2d269c8afff4db74a'
BACKEND_ID = 'gba-anygba-probe'
GAME_BACKEND_ID = 'gba-anygba-experimental'
PROFILE_SCHEMA = 'decomp.wtf.gba-profile/v1'
SAVE_TYPES = ('auto', 'none', 'sram', 'flash64', 'flash128', 'eeprom', 'eeprom512', 'eeprom8k')
_progress = ContextVar('gba_native_progress', default=None)
RUNTIME_DIRS = ('apu', 'ppu', 'bios', 'save', 'state', 'interp', 'cheats')
CORE = ('runtime', 'system', 'bus', 'io_regs', 'scheduler', 'irq', 'dma', 'timers',
        'cpu_state', 'dispatch', 'rom_patch', 'rtc')


def _log(message):
    callback = _progress.get()
    if callback is None:
        print(message, file=sys.stderr)
    else:
        callback(message)


def _source(name):
    return resources.files(__package__).joinpath(name).read_text(encoding='utf-8')


def revision():
    value = hashlib.sha256(SDK_COMMIT.encode())
    for name in ('__init__.py', 'Emitter.cmake', 'Project.cmake', 'main.cpp', 'extract.py',
                 'video.hpp', 'video.cpp', 'ppu.frag', 'shader.hpp.in', 'graphics_tests.cpp', 'cartridge_tests.cpp', 'ram_feedback.hpp', 'overlay_emitter.cpp', 'bios_image.cpp', 'timing.cpp', 'discovery.inc', 'copy_discovery.cpp', 'bios_native.h', 'bios_emitter.cpp', 'native_entries.cpp', 'relocated.h', 'relocated.cpp', 'relocated_runtime.cpp', 'native_idle.hpp',
                 'cheats.hpp', 'cheats.cpp', 'settings_win32.cpp', 'customization.hpp', 'customization.cpp', 'cheat_tests.cpp', 'tomlplusplus-license.txt'):
        value.update(name.encode()+b'\0'+_source(name).encode())
    return value.hexdigest()


def inspect(path):
    path = Path(path)
    size = path.stat().st_size
    if not 0xc0 <= size <= 32*1024*1024 or size % 2:
        raise pc.PCError('GBA cartridges must be an even size from 192 bytes through 32 MiB')
    data = path.read_bytes()
    if not is_gba(data):
        raise pc.PCError('GBA cartridge entry, fixed byte or header checksum is invalid')
    info = read_info(data)
    return dict(platform='gba', title=info['title'], game_code=info['game_code'], version=info['version'],
                input=dict(size=len(data), sha256=hashlib.sha256(data).hexdigest()),
                native_game_backend_available=True, retail_qualified=False)


def _cmake(*, platform=None, program_files=None):
    """Use Visual Studio's bundled CMake when it is absent from Windows PATH."""
    if program := shutil.which('cmake'):
        return program
    if (platform or sys.platform) == 'win32':
        folder = program_files or os.environ.get('ProgramFiles(x86)')
        if folder:
            locator = Path(folder)/'Microsoft Visual Studio/Installer/vswhere.exe'
            if locator.is_file():
                try:
                    result = subprocess.run([str(locator), '-utf8', '-products', '*', '-find',
                        r'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'],
                        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            candidate = Path(line.strip())
                            if candidate.is_file():
                                return str(candidate)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    raise pc.PCError('CMake 3.20+ is required: https://cmake.org/download/ . '
        'On Windows, enable C++ CMake tools for Windows in Visual Studio Installer; '
        'a separate CMake download is unnecessary when that component is installed.')


def _run(command, cwd, what):
    _log(what+'...')
    command = list(command)
    if command[0] == 'cmake':
        command[0] = _cmake()
    try:
        result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=600)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise pc.PCError(what+' failed: '+str(error)) from error
    output = result.stdout+result.stderr
    if result.returncode:
        raise pc.PCError(what+' failed:\n'+output[-4000:])
    return output


def _sdk():
    try:
        sdk = toolchains.ensure('anygba-sdk', log=_log)
    except toolchains.ToolchainError as error:
        raise pc.PCError(str(error)) from error
    if _fingerprint(sdk) != SDK_TREE_SHA256:
        raise pc.PCError('GBA cached sources differ from the pinned SDK; preserve edits and reinstall in a clean cache')
    return sdk


def _fingerprint(sdk):
    """The cache cannot silently change between source generation and compilation."""
    value = hashlib.sha256()
    for base in ('common', 'tools/recomp', 'runtime'):
        # WindowsPath sorts case-insensitively. Pin one order on every host.
        for path in sorted((sdk/base).rglob('*'), key=lambda p: p.relative_to(sdk).as_posix()):
            if path.is_symlink():
                raise pc.PCError('GBA source cache contains an external source')
            if path.is_file():
                value.update(path.relative_to(sdk).as_posix().encode()+b'\0'+path.read_bytes())
    value.update((sdk/'LICENSE').read_bytes())
    return value.hexdigest()


def _emitter(sdk):
    emitter_key = hashlib.sha256((SDK_TREE_SHA256+_source('Emitter.cmake')+_source('overlay_emitter.cpp')+_source('discovery.inc')+_source('copy_discovery.cpp')+_source('bios_emitter.cpp')+_source('native_entries.cpp')+_source('relocated.cpp')).encode()).hexdigest()
    work = sdk.parent/'.gba-emitter'/emitter_key[:16]
    work.mkdir(parents=True, exist_ok=True)
    identity = dict(commit=SDK_COMMIT, sha256=_fingerprint(sdk))
    marker = work/'source.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) != identity:
        raise pc.PCError('GBA cached sources changed; preserve edits and choose a clean toolchain cache')
    (work/'CMakeLists.txt').write_text(_source('Emitter.cmake'), encoding='utf-8')
    (work/'overlay_emitter.cpp').write_text(_source('overlay_emitter.cpp'), encoding='utf-8')
    (work/'discovery.inc').write_text(_source('discovery.inc'), encoding='utf-8')
    (work/'copy_discovery.cpp').write_text(_source('copy_discovery.cpp'), encoding='utf-8')
    (work/'bios_emitter.cpp').write_text(_source('bios_emitter.cpp'), encoding='utf-8')
    (work/'native_entries.cpp').write_text(_source('native_entries.cpp'), encoding='utf-8')
    (work/'relocated.cpp').write_text(_source('relocated.cpp'), encoding='utf-8')
    _run(['cmake', '-S', work, '-B', work/'build', '-DGBA_SDK='+sdk.as_posix(),
          '-DCMAKE_BUILD_TYPE=Release'], work, 'Configure GBA static translator')
    _run(['cmake', '--build', work/'build', '--target', 'anygba-recomp', 'gba-overlays', 'gba-copies', 'gba-bios', '--config', 'Release',
          '--parallel', '2'], work, 'Build GBA static translator')
    marker.write_text(json.dumps(identity)+'\n', encoding='utf-8')
    executable = next((p for p in (work/'build/recomp/anygba-recomp',
        work/'build/recomp/Release/anygba-recomp.exe', work/'build/recomp/anygba-recomp.exe') if p.is_file()), None)
    if executable is None:
        raise pc.PCError('GBA static translator was not built')
    return executable


def _emitter_tool(emitter,name):
    filename=name+('.exe' if emitter.suffix=='.exe' else '')
    if emitter.parent.name=='Release':
        return emitter.parent.parent.parent/'Release'/filename
    return emitter.parent.parent/filename


def _automatic_copies(emitter,path,work,size):
    result=json.loads(_run([_emitter_tool(emitter,'gba-copies'),path],work,
        'Infer guarded ROM-to-RAM code copies'))
    _regions(dict(ram_code=result['copies'],entries=[]),size)
    return result['copies'],result['entries'],result['rom_entries']


def _overlay_regions(profile, feedback, size):
    """Independent views retain temporal copies instead of clipping at other entries."""
    copies = {(r['address'], r['mode'], r['rom']): r['size'] for r in profile.get('ram_code', [])}
    reviewed = set(copies)
    for content, _ in feedback:
        for line in content.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 3:
                continue
            address, mode, source = int(fields[0], 16), fields[1], int(fields[2][4:], 16)
            end = 0x02040000 if address < 0x03000000 else 0x03008000
            width = 4 if mode == 'arm' else 2
            length = min(end-address, 0x08000000+size-source)//width*width
            if len(fields) == 4:
                length = min(length, int(fields[3][5:], 16))
            key = address, mode, source
            if key in reviewed:
                continue
            copies[key] = min(copies.get(key, length), length)
    if len(copies) > 4096:
        raise pc.PCError('GBA feedback contains too many distinct RAM copies (maximum 4096)')
    return [dict(address=a, mode=m, rom=r, size=n) for (a,m,r),n in sorted(copies.items()) if n]


def _overlays(emitter, path, work, root, copies, profile, feedback, instruction_regions=()):
    config = ''
    for row in copies:
        config += f'\n[[ram_region]]\nrom_src = {row["rom"]}\nram_dst = {row["address"]}\nsize = {row["size"]}\nmode = "{row["mode"]}"\n'
    entries = {(r['address'],r['mode']) for r in profile.get('entries', []) if r['address'] < 0x08000000}
    for content, _ in feedback:
        for line in content.splitlines()[1:]:
            fields=line.split()
            if fields and int(fields[0],16)<0x08000000:
                entries.add((int(fields[0],16),fields[1]))
    for address, mode in sorted(entries):
        config += f'\n[[entry]]\naddr = {address}\nmode = "{mode}"\n'
    cfg = work/'overlays.toml'; cfg.write_text(config, encoding='utf-8')
    program = _emitter_tool(emitter,'gba-overlays')
    bounded=work/'bounded-instruction-regions.txt'
    bounded.write_text(''.join(f'{source} {address} {size}\n' for source,address,size in sorted({
        (r['rom'],r['address'],r['size']) for r in instruction_regions})),encoding='utf-8')
    rows = json.loads(_run([program, path, cfg, root/'game/overlays.c',bounded], work, 'Translate independent guarded RAM copies'))
    header = root/'game/game.h'
    header.write_text(header.read_text(encoding='utf-8')+'\n'+''.join(
        f'void {name}(anygba_cpu* c);\n' for name in sorted({r[2] for r in rows})), encoding='utf-8')
    dispatch = root/'game/dispatch.c'
    text = dispatch.read_text(encoding='utf-8')
    begin = text.index('static const anygba_function_entry functions[] = {\n') + len('static const anygba_function_entry functions[] = {\n')
    # Complete, independently analyzed copies take precedence over a clipped base
    # view. The runtime stable-sorts by address, then checks every candidate's bytes.
    text = text[:begin]+''.join(f'    {{{a}u, {t}, {n}, {b}u, {e}u, {s}u}},\n' for a,t,n,b,e,s in rows)+text[begin:]
    old_count = len(re.findall(r'^    \{0x[0-9a-f]{8}u,', text[begin:], re.M))
    pattern = r'(    functions,\n    )\d+u,'
    text, count = re.subn(pattern, lambda m: m[1]+str(old_count+len(rows))+'u,', text)
    if count != 1:
        raise pc.PCError('GBA guarded dispatch table patch no longer applies')
    dispatch.write_text(text, encoding='utf-8')
    return len({r[2].removesuffix('_resume') for r in rows})


def _fragment_dispatch(root, *, max_bytes=1024*1024):
    """Keep large generated tables in ordinary Git without changing their C layout."""
    path = root/'game/dispatch.c'
    if path.stat().st_size <= max_bytes:
        return
    text = path.read_text(encoding='utf-8')
    marker = 'static const anygba_function_entry functions[] = {\n'
    begin = text.find(marker)
    if begin < 0:
        raise pc.PCError('GBA native dispatch table marker differs')
    begin += len(marker)
    end = text.find('};\n', begin)
    if end < 0:
        raise pc.PCError('GBA native dispatch table terminator differs')
    fragments = []
    offset = begin
    while offset < end:
        stop = min(offset+max_bytes, end)
        if stop < end:
            stop = text.rfind('\n', offset, stop)+1
        if stop <= offset:
            raise pc.PCError('GBA native dispatch entry exceeds the source fragment budget')
        fragments.append(text[offset:stop])
        offset = stop
    includes = []
    for index, fragment in enumerate(fragments):
        name = f'dispatch_entries_{index:03d}.inc'
        (path.parent/name).write_text(fragment, encoding='utf-8', newline='\n')
        includes.append(f'#include "{name}"\n')
    path.write_text(text[:begin]+''.join(includes)+text[end:], encoding='utf-8', newline='\n')


def _profile(path, identity):
    if path is None:
        return {}
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('schema') != PROFILE_SCHEMA:
        raise pc.PCError('unsupported GBA analysis profile')
    if document.get('input_sha256') != identity:
        raise pc.PCError('GBA profile ROM SHA-256 differs from input')
    if set(document) - {'schema', 'input_sha256', 'entries', 'ram_code'}:
        raise pc.PCError('GBA profiles accept only code entries and ROM-to-RAM code copies')
    for key, fields in (('entries', {'address', 'mode'}), ('ram_code', {'rom', 'address', 'size', 'mode'})):
        rows = document.get(key, [])
        if not isinstance(rows, list) or len(rows) > 100000:
            raise pc.PCError('GBA profile entries must be a bounded list')
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields or row.get('mode') not in ('arm', 'thumb'):
                raise pc.PCError('invalid GBA code entry')
            if any(type(v) is not int or not 0 <= v <= 0xffffffff for k, v in row.items() if k != 'mode'):
                raise pc.PCError('GBA code addresses and sizes must be unsigned 32-bit integers')
            if row['address'] % (4 if row['mode'] == 'arm' else 2):
                raise pc.PCError('GBA code entry is misaligned')
    return document


def _regions(profile, size):
    ranges = []
    for row in profile.get('ram_code', []):
        address, length, rom = row['address'], row['size'], row['rom']
        alignment = 4 if row['mode'] == 'arm' else 2
        if (length == 0 or length % alignment or rom % alignment or
            not 0x08000000 <= rom < rom+length <= 0x08000000+size or
            not any(begin <= address < address+length <= end for begin, end in
                    ((0x02000000, 0x02040000), (0x03000000, 0x03008000)))):
            raise pc.PCError('GBA RAM code must copy aligned original ROM bytes into EWRAM/IWRAM')
        ranges.append((address, address+length))
    for row in profile.get('entries', []):
        width = 4 if row['mode'] == 'arm' else 2
        if not any(begin <= row['address'] and row['address']+width <= end
                   for begin, end in [(0x08000000, 0x08000000+size), *ranges]):
            raise pc.PCError('GBA code entry lies outside the cartridge and mapped RAM code')


def _feedback(path, identity, size):
    path = Path(path)
    if path.stat().st_size > 16*1024*1024:
        raise pc.PCError('GBA coverage feedback is too large')
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    if not lines or lines[0] != '# decomp.wtf.gba-misses/v1 sha256='+identity:
        raise pc.PCError('GBA feedback ROM SHA-256 differs or its identity header is missing')
    count = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        match = re.fullmatch(r'(0x[0-9a-fA-F]{8}) (arm|thumb)(?: rom=(0x[0-9a-fA-F]{8})(?: size=(0x[0-9a-fA-F]{1,8}))?)?', line)
        if match is None:
            raise pc.PCError('invalid GBA coverage feedback record')
        address = int(match[1], 16)
        width = 4 if match[2] == 'arm' else 2
        in_rom = 0x08000000 <= address < 0x0e000000
        in_ram = any(a <= address and address+width <= b for a, b in
                     ((0x02000000, 0x02040000), (0x03000000, 0x03008000)))
        if (address % width or not (in_rom or in_ram) or
            (in_rom and (address & 0x1ffffff)+width > size)):
            raise pc.PCError('GBA feedback code address is misaligned or outside the input')
        if match[3] is not None:
            source = int(match[3], 16)
            if not in_ram or source % width or not 0x08000000 <= source <= 0x08000000+size-width:
                raise pc.PCError('GBA feedback RAM source lies outside the input')
            if match[4] is not None:
                length = int(match[4], 16)
                end = 0x02040000 if address < 0x03000000 else 0x03008000
                if not 0 < length <= 32 or length % width or source+length > 0x08000000+size or address+length > end:
                    raise pc.PCError('GBA feedback RAM signature size is misaligned or outside the input/RAM')
        count += 1
        if count > 100000:
            raise pc.PCError('GBA coverage feedback has too many records')
    return text, dict(sha256=hashlib.sha256(text.encode()).hexdigest(), records=count)


def _feedback_regions(profile, feedback, size):
    """Bound RAM hints at every observed entry; never let log order hide another copy.

    The upstream miss reader maps a copy through the end of RAM. Later hints can
    obscure earlier, unrelated copies. Install disjoint hints up front instead;
    generated byte guards still verify every native function before execution.
    Conflicting sources for one address remain interpreted unless profiled.
    """
    hints = {}
    for content, _ in feedback:
        for line in content.splitlines()[1:]:
            fields = line.split()
            if not fields:
                continue
            address = int(fields[0], 16)
            if 0x02000000 <= address < 0x04000000:
                sources = hints.setdefault(address, {})
                if len(fields) >= 3:
                    lengths = sources.setdefault((int(fields[2][4:], 16), fields[1]), set())
                    lengths.add(int(fields[3][5:], 16) if len(fields)==4 else 0)
    reviewed = profile.get('ram_code', [])
    boundaries = sorted({*hints, *[r['address'] for r in reviewed], 0x02040000, 0x03008000})
    regions = []
    for index, address in enumerate(boundaries):
        if address not in hints or len(hints[address]) != 1:
            continue
        if any(r['address'] <= address < r['address']+r['size'] for r in reviewed):
            continue
        (source, mode), lengths = next(iter(hints[address].items()))
        end = min(boundaries[index+1], 0x02040000 if address < 0x03000000 else 0x03008000)
        width = 4 if mode == 'arm' else 2
        length = min(end-address, 0x08000000+size-source)//width*width
        bounds = [n for n in lengths if n]
        if bounds:
            length = min(length, min(bounds))
        if length:
            # A function can cross an interior observed entry. Keep contiguous
            # bytes from the same ROM copy together so its whole-body byte guard
            # can resolve one original source span.
            if (regions and regions[-1]['address']+regions[-1]['size'] == address and
                regions[-1]['rom']+regions[-1]['size'] == source):
                regions[-1]['size'] += length
            else:
                regions.append(dict(rom=source, address=address, size=length, mode=mode))
    return regions


def _runtime(sdk, destination):
    destination.mkdir(parents=True)
    for folder in ('runtime/include', 'common/include', 'tools/recomp/decode'):
        shutil.copytree(sdk/folder, destination/folder)
    for folder in RUNTIME_DIRS:
        shutil.copytree(sdk/'runtime/src'/folder, destination/'runtime/src'/folder)
    for name in CORE:
        shutil.copyfile(sdk/'runtime/src'/(name+'.cpp'), destination/'runtime/src'/(name+'.cpp'))
    shutil.copyfile(sdk/'runtime/src/rtc.h', destination/'runtime/src/rtc.h')
    (destination/'common/src').mkdir(parents=True)
    for name in ('sha256.cpp', 'crc32.cpp'):
        shutil.copyfile(sdk/'common/src'/name, destination/'common/src'/name)
    shutil.copyfile(sdk/'LICENSE', destination/'LICENSE')
    # Strict qualification must detect misses and unsupported services immediately.
    header = destination/'runtime/include/anygba/system.hpp'
    text = header.read_text(encoding='utf-8')
    old = 'struct Options {'
    if text.count(old) != 1:
        raise pc.PCError('GBA runtime option patch no longer applies')
    text = text.replace(old, old+'\n    bool strict_static = false;\n    const anygba_bios* compiled_bios = nullptr;\n'
        '    const anygba_relocated_entry* relocated_entries = nullptr;\n    uint32_t relocated_count = 0;')
    text = text.replace('#include <vector>', '#include <vector>\n#include <tuple>\n#include "anygba/bios_native.h"\n#include "anygba/relocated.h"')
    text=text.replace('std::vector<const anygba_function_entry*> rom_direct_;',
        'std::vector<std::array<const anygba_function_entry*,2>> rom_direct_;')
    text = text.replace('bool ram_code_valid(std::uint32_t entry, bool thumb) const;',
        'bool ram_code_valid(std::uint32_t entry, bool thumb) const;\n    bool ram_entry_valid(const anygba_function_entry& entry) const;\n'
        '    anygba_fn lookup_relocated(std::uint32_t entry, bool thumb) const;\n'
        '    uint64_t bios_native_instructions() const { return bios_native_instructions_; }')
    text = text.replace('std::set<std::uint32_t> misses_;',
        'bool bios_image_loaded_ = false;\n    bool bios_native_image_ = false;\n    uint64_t bios_native_instructions_ = 0;\n    unsigned bios_irq_depth_ = 0;\n    std::set<std::uint32_t> misses_;\n    std::set<std::tuple<uint32_t,bool,uint32_t,uint32_t>> logged_miss_variants_;\n'
        '    std::set<std::tuple<uint32_t,bool,std::array<uint8_t,32>>> logged_ram_signatures_;')
    text = text.replace('static constexpr std::uint32_t kStateVersion = 2;',
                        'static constexpr std::uint32_t kStateVersion = 1002;')
    text = text.replace('    void set_cpsr(',
        '    void memory_load_events();\n    void set_bios_image(std::span<const uint8_t> image);\n    void bios_swi();\n    void set_cpsr(')
    text = text.replace('    void bios_swi();',
        '    void bios_swi();\n    void bios_irq(uint32_t return_pc);\n    void bios_prefetch(uint32_t address, bool thumb);\n'
        '    void validate_bios_native();\n    void bios_native_enter(uint32_t address, bool thumb);')
    text = text.replace('ignores ROM patches and RAM contents', 'ignores ROM patches; checks RAM variants')
    header.write_text(text, encoding='utf-8')
    system = destination/'runtime/src/system.cpp'
    text = system.read_text(encoding='utf-8')
    text=text.replace('rom_direct_.assign(mem_.rom_size / 2 + 1, nullptr);',
        'rom_direct_.assign(mem_.rom_size / 2 + 1, std::array<const anygba_function_entry*,2>{});')
    text=text.replace('rom_direct_[(e.addr - 0x08000000) / 2] = &e;',
        'rom_direct_[(e.addr - 0x08000000) / 2][e.thumb!=0] = &e;')
    system.write_text(text.replace('std::sort(ram_functions_.begin(), ram_functions_.end(),',
        'std::stable_sort(ram_functions_.begin(), ram_functions_.end(),'), encoding='utf-8')
    dispatch = destination/'runtime/src/dispatch.cpp'
    text = dispatch.read_text(encoding='utf-8')
    text = '#include "ram_feedback.hpp"\n'+text
    text=text.replace('rom_direct_[off / 2];','rom_direct_[off / 2][thumb];')
    old='return e ? e->fn : nullptr;'
    if text.count(old)!=1:raise pc.PCError('GBA relocated dispatch patch no longer applies')
    text=text.replace(old,'return e ? e->fn : lookup_relocated(addr,thumb);')
    text = text.replace('bool System::in_irq_handler() const {',
        'bool System::in_irq_handler() const {\n    if (bios_irq_depth_) return true;')
    text = text.replace('    cpu_.ret_depth = 0;', '    cpu_.ret_depth = 0;\n    bios_irq_depth_ = 0;')
    start = text.index('    if (fn && (addr < 0x08000000')
    end = text.index('    if (fn && cpu_.rom_patched', start)
    text = text[:start]+text[end:]
    old = '    if (!game_) {\n        return nullptr;\n    }'
    if text.count(old)!=1:raise pc.PCError('GBA compiled firmware dispatch patch no longer applies')
    text=text.replace(old,old+'''
    if (addr < Memory::kBiosSize && bios_native_image_) {
        if (thumb) return (addr & 1u) ? nullptr : options_.compiled_bios->thumb[addr / 2];
        return (addr & 3u) ? nullptr : options_.compiled_bios->arm[addr / 4];
    }''')
    start = text.index('    if (it != ram_functions_.end()')
    end = text.index('    return nullptr;', start)
    text = text[:start]+'''    for (auto candidate=it; candidate!=ram_functions_.end() && candidate->addr==addr; ++candidate) {
        if ((candidate->thumb!=0)==thumb && ram_entry_valid(*candidate)) return &*candidate;
    }
'''+text[end:]
    old = '''bool System::ram_code_valid(std::uint32_t entry, bool thumb) const {
    const anygba_function_entry* e = ram_function(entry, thumb);'''
    if text.count(old) != 1:
        raise pc.PCError('GBA overlay byte guard patch no longer applies')
    text = text.replace(old, '''bool System::ram_code_valid(std::uint32_t entry, bool thumb) const {
    return ram_function(entry,thumb)!=nullptr;
}

bool System::ram_entry_valid(const anygba_function_entry& entry) const {
    const anygba_function_entry* e = &entry;''')
    text = text.replace('if (!misses_.insert(addr).second || !options_.log_misses) {',
        'misses_.insert(addr);\n    if (!options_.log_misses) {')
    text = text.replace('void System::log_miss(std::uint32_t addr, bool thumb) {',
        'void System::log_miss(std::uint32_t addr, bool thumb) {\n    if (addr < 0x02000000) return; // BIOS code is not cartridge coverage feedback')
    start = text.index('    char rom_part[24] = "";')
    end = text.index('    std::fprintf(miss_file_', start)
    text = text[:start]+'''    char rom_part[64] = "";
    uint32_t source=0, length=0;
    const bool ewram = addr >= 0x02000000 && addr < 0x02040000;
    const bool iwram = addr >= 0x03000000 && addr < 0x03008000;
    if (ewram || iwram) {
        const auto& ram = ewram ? mem_.ewram : mem_.iwram;
        const auto off = addr & 0x00ffffffu;
        const auto view=std::span<const uint8_t>(ram.data()+off,ram.size()-off);
        const auto leaf=gba_feedback::leaf_size(view,thumb);
        std::array<uint8_t,32> signature{};
        std::copy_n(view.begin(),leaf?leaf:std::min<size_t>(32,view.size()),signature.begin());
        if (!logged_ram_signatures_.emplace(addr,thumb,signature).second) return;
        const auto hit = gba_feedback::source(std::span<const uint8_t>(mem_.rom.data(),mem_.rom_size),
            view,thumb);
        if (hit) {
            source=hit->address; length=hit->size;
            if (hit->size) std::snprintf(rom_part,sizeof rom_part," rom=0x%08x size=0x%08x",hit->address,hit->size);
            else std::snprintf(rom_part,sizeof rom_part," rom=0x%08x",hit->address);
        }
    }
    if (!logged_miss_variants_.emplace(addr,thumb,source,length).second) return;
'''+text[end:]
    old = 'void System::interpret() {'
    if text.count(old) != 1:
        raise pc.PCError('GBA interpreter guard patch no longer applies')
    dispatch.write_text(text.replace(old, old+'\n    if (options_.strict_static) {\n'
        '        fail("static coverage miss at " + std::to_string(cpu_.r[15]));\n    }'), encoding='utf-8')
    text = dispatch.read_text(encoding='utf-8')
    for old, new in (
        ('!resuming_ && !lookup_compiled(cpu_.r[15], cpu_.t != 0)',
         '!resuming_ && !lookup(cpu_.r[15], cpu_.t != 0)'),
        ('call && !lookup_compiled(cpu_.r[15], cpu_.t != 0)',
         'call && !lookup(cpu_.r[15], cpu_.t != 0)'),
    ):
        if text.count(old) != 1:
            raise pc.PCError('GBA guarded-code feedback patch no longer applies')
        text = text.replace(old, new)
    old = 'options_.log_misses = false;\n            return;'
    if text.count(old) != 1:
        raise pc.PCError('GBA feedback error patch no longer applies')
    text = text.replace(old, 'fail("cannot append GBA coverage feedback");')
    old = '    std::fflush(miss_file_);'
    if text.count(old) != 1:
        raise pc.PCError('GBA feedback flush patch no longer applies')
    text=text.replace(old,
        '    if (std::fflush(miss_file_) != 0 || std::ferror(miss_file_)) fail("GBA coverage feedback write failed");')
    start=text.index('void System::interpret() {')+len('void System::interpret() {')
    end=text.index('\n}\n\n}  // namespace anygba',start)
    text=text[:start]+'''
#ifndef ANYGBA_ENABLE_REFERENCE
    fail("static coverage miss at " + std::to_string(cpu_.r[15]) +
         "; this player contains no interpreter. Use the explicit reference probe to collect coverage for re-export.");
#else
'''+text[start:end]+'\n#endif'+text[end:]
    dispatch.write_text(text,encoding='utf-8')
    bios = destination/'runtime/src/bios/swi_table.cpp'
    text = bios.read_text(encoding='utf-8')
    text = text.replace('void System::swi(std::uint32_t number) {',
        'void System::swi(std::uint32_t number) {\n    if (bios_image_loaded_) { bios_swi(); return; }')
    text = text.replace('    case 0x25:\n        stub_swi(number, call_pc);',
        '    case 0x25:')  # A disconnected cable is a normal MultiBoot failure.
    old = 'void System::stub_swi(std::uint32_t number, std::uint32_t call_pc) {'
    if text.count(old) != 1:
        raise pc.PCError('GBA BIOS guard patch no longer applies')
    bios.write_text(text.replace(old, old+'\n    fail("unsupported GBA BIOS service " + std::to_string(number) +'
        ' " at " + std::to_string(call_pc) + "; provide your own GBA BIOS with --bios for this service");'), encoding='utf-8')
    (destination/'runtime/src/bios_image.cpp').write_text(_source('bios_image.cpp'), encoding='utf-8')
    (destination/'runtime/include/anygba/bios_native.h').write_text(_source('bios_native.h'),encoding='utf-8')
    (destination/'runtime/include/anygba/relocated.h').write_text(_source('relocated.h'),encoding='utf-8')
    (destination/'runtime/src/relocated.cpp').write_text(_source('relocated_runtime.cpp'),encoding='utf-8')
    (destination/'runtime/src/timing.cpp').write_text(_source('timing.cpp'), encoding='utf-8')
    cpu_header = destination/'runtime/include/anygba/cpu.h'
    text = cpu_header.read_text(encoding='utf-8')
    cpu_header.write_text(text.replace('void anygba_tick(anygba_cpu* c);',
        'void anygba_tick(anygba_cpu* c);\nvoid anygba_load_events(anygba_cpu* c);\n'
        'int anygba_ram_variant_valid(anygba_cpu* c, uint32_t begin, uint32_t end, uint32_t source);'), encoding='utf-8')
    rom_patch = destination/'runtime/src/rom_patch.cpp'
    text = rom_patch.read_text(encoding='utf-8')
    text += '''
extern "C" int anygba_ram_variant_valid(anygba_cpu* c, uint32_t begin, uint32_t end, uint32_t source) {
    const anygba_function_entry entry{0,0,nullptr,begin,end,source};
    return anygba::system_of(c).ram_entry_valid(entry) ? 1 : 0;
}
'''
    rom_patch.write_text(text, encoding='utf-8')
    interp = destination/'runtime/src/interp/arm_interp.cpp'
    text = interp.read_text(encoding='utf-8')
    text = text.replace('        if (load) {\n            std::uint32_t v = 0;',
        '        if (load) {\n            if (--c_.cycles <= 0) sys_.memory_load_events();\n            std::uint32_t v = 0;')
    text = text.replace('case Op::LDR: case Op::LDRB: case Op::LDRH: case Op::LDRSB: case Op::LDRSH: extra = 1; break;',
        'case Op::LDR: case Op::LDRB: case Op::LDRH: case Op::LDRSB: case Op::LDRSH: extra = 0; break;')
    # SWI runs a synchronous firmware service, which can observe timers or
    # transfer audio before returning. Charge its issuing instruction first.
    old = '        if (passes(c_, in_.cond)) {\n            dispatch();'
    if text.count(old) != 1:
        raise pc.PCError('GBA reference software-interrupt timing patch no longer applies')
    text = text.replace(old,
        '        if (passes(c_, in_.cond)) {\n'
        '            if (in_.op == Op::SWI) {\n'
        '                charge();\n                dispatch();\n                return;\n            }\n'
        '            dispatch();')
    interp.write_text(text, encoding='utf-8')
    fetch = destination/'runtime/src/interp/thumb_interp.cpp'
    text = fetch.read_text(encoding='utf-8')
    old = 'decode::Insn fetch(System& sys, std::uint32_t addr, bool thumb) {'
    if text.count(old) != 1:
        raise pc.PCError('GBA BIOS instruction latch patch no longer applies')
    fetch.write_text(text.replace(old, old+'\n    sys.bios_prefetch(addr, thumb);'), encoding='utf-8')
    irq = destination/'runtime/src/irq.cpp'
    text = irq.read_text(encoding='utf-8')
    old = '    c.r[14] = resume_pc + 4;'
    if text.count(old) != 1:
        raise pc.PCError('GBA BIOS interrupt vector patch no longer applies')
    irq.write_text(text.replace(old, old+'\n    if (bios_image_loaded_) { bios_irq(resume_pc); return; }'), encoding='utf-8')
    bus = destination/'runtime/src/bus.cpp'
    text = bus.read_text(encoding='utf-8')
    for name, width in (('bus_read32', 4), ('bus_read16', 2), ('bus_read8', 1)):
        start = text.index('std::uint32_t System::'+name+'(')
        case = text.index('    case 0x00:\n', start)+len('    case 0x00:\n')
        text = text[:case]+f'        if (bios_image_loaded_ && addr < Memory::kBiosSize && cpu_.r[15] < Memory::kBiosSize) return load(mem_.bios, addr, {width});\n'+text[case:]
    bus.write_text(text, encoding='utf-8')
    state = destination/'runtime/src/state/state.cpp'
    text = state.read_text(encoding='utf-8')
    state.write_text(text.replace('    ar.fixed(mem_.bios, "BIOS area");',
        '    ar.pod(bios_image_loaded_);\n    ar.fixed(mem_.bios, "BIOS area");\n    if (ar.loading()) validate_bios_native();'), encoding='utf-8')
    rtc = destination/'runtime/src/rtc.cpp'
    text = rtc.read_text(encoding='utf-8')
    text = text.replace('    case 0xC4:\n', '    case 0xC4: {\n        const auto previous=pins_;\n')
    text = text.replace('        clock_pins();\n        break;', '        clock_pins(previous);\n        break;\n    }')
    start = text.index('void Rtc::clock_pins() {')
    end = text.index('\nvoid Rtc::command_byte()', start)
    text = text[:start]+'''void Rtc::clock_pins(std::uint16_t previous) {
    if (step_==0) {
        if ((pins_ & (kSck|kCs))==kSck) step_=1;
        return;
    }
    if (step_==1) {
        if ((pins_ & (kSck|kCs))==(kSck|kCs)) step_=2;
        else if ((pins_ & (kSck|kCs))!=kSck) step_=0;
        return;
    }
    // CS terminates even when the clock is low. Only a rising clock edge
    // transfers a bit; repeated high GPIO writes must not advance the chip.
    if (!(pins_ & kCs)) {
        bits_=bit_count_=remaining_=command_=0;
        step_=pins_ & kSck;
        return;
    }
    if ((previous & kSck) || !(pins_ & kSck)) return;
    if (is_read(command_)) {
        const auto output=kSck|kCs|(output_bit()<<1);
        pins_=std::uint16_t((pins_ & direction_) | (output & ~direction_ & 0xf));
        if (++bit_count_==8) {
            bit_count_=0;
            if (remaining_<=1) remaining_=command_=0;
            else --remaining_;
        }
    } else {
        bits_=std::uint8_t((bits_ & ~(1u<<bit_count_)) | (((pins_ & kSio)>>1)<<bit_count_));
        if (++bit_count_==8) command_byte();
    }
}
'''+text[end:]
    rtc.write_text(text, encoding='utf-8')
    rtc_header = destination/'runtime/src/rtc.h'
    rtc_header.write_text(rtc_header.read_text(encoding='utf-8').replace('void clock_pins();',
        'void clock_pins(std::uint16_t previous);'), encoding='utf-8')
    (destination/'DECOMP_WTF_PATCHES.md').write_text(
        'Pinned AnyGBA '+SDK_COMMIT+' (MIT).\n\n'
        'This source-shipped core omits the upstream player, network control, cheats and HD packs. '
        'Options.strict_static rejects interpreter execution. Independent temporal RAM copies have whole-body guards, including on direct entry. '
        'Coverage records retain multiple bodies at one address and cache repeated signatures. '
        'Instruction and load phases synchronize peripheral events. RTC GPIO transfers require clock edges and honor chip-select aborts. '
        'An optional owner BIOS can be translated ahead of time, including software-interrupt vectors, Thumb entries, IRQ return and protected reads. '
        'Only an exact matching image uses compiled firmware dispatch; an explicitly supplied unmatched image remains reported interpretation and is rejected by strict mode. '
        'Without that image, unsupported sound services stop with an actionable diagnostic; disconnected MultiBoot returns failure. '
        'Internal snapshots use format 1002 to record BIOS selection. The independent desktop frontend renders raw scanline state with OpenGL.\n', encoding='utf-8')


def generate(project, root):
    path = Path(project['input']).resolve()
    inspection = inspect(path)
    original = inspection['input']
    bios=Path(project['bios']).expanduser().resolve() if project.get('bios') is not None else None
    bios_identity=None
    if bios is not None:
        if not bios.is_file() or bios.stat().st_size!=16384:raise pc.PCError('GBA BIOS must be an existing 16384-byte file')
        bios_identity=dict(kind='bios',size=16384,sha256=hashlib.sha256(bios.read_bytes()).hexdigest())
    profile = _profile(project.get('profile'), original['sha256'])
    _regions(profile, original['size'])
    feedback = [_feedback(p, original['sha256'], original['size']) for p in project.get('feedback', [])]
    inferred = _feedback_regions(profile, feedback, original['size'])
    copies = _overlay_regions(profile, feedback, original['size'])
    game = project.get('output_kind') == 'game'
    display = pc.presentation(project.get('renderer', 'auto')) if game else None
    save_type = project.get('save_type', 'auto')
    rtc = project.get('rtc', 'auto')
    if save_type not in SAVE_TYPES or rtc not in ('auto', 'on', 'off'):
        raise pc.PCError('invalid GBA save chip or clock selection')
    sdk = _sdk(); emitter = _emitter(sdk)
    for name in ('game', 'native', 'tools', 'tests'):
        (root/name).mkdir()
    with tempfile.TemporaryDirectory(prefix='.gba-analysis-', dir=root.parent) as tmp:
        work = Path(tmp)
        automatic,automatic_entries,automatic_rom_entries=_automatic_copies(emitter,path,work,original['size'])
        copies=[dict(address=a,mode=m,rom=r,size=n) for a,m,r,n in sorted({
            (row['address'],row['mode'],row['rom'],row['size']) for row in [*copies,*automatic]})]
        if len(copies)>4096:raise pc.PCError('too many independent RAM code copies')
        config = '[game]\ntitle = '+json.dumps(inspection['title'])+'\n'
        if save_type != 'auto':
            config += 'save = '+json.dumps(save_type)+'\n'
        if rtc != 'auto':
            config += 'rtc = '+('true' if rtc == 'on' else 'false')+'\n'
        for row in [*profile.get('entries', []),*automatic_rom_entries]:
            config += f'\n[[entry]]\naddr = {row["address"]}\nmode = "{row["mode"]}"\n'
        for row in [*profile.get('ram_code', []), *inferred]:
            config += f'\n[[ram_region]]\nrom_src = {row["rom"]}\nram_dst = {row["address"]}\nsize = {row["size"]}\nmode = "{row["mode"]}"\n'
        cfg = work/'game.toml'; cfg.write_text(config, encoding='utf-8')
        command = [emitter, path, '--config', cfg, '--output', work/'generated']
        for index, (content, _) in enumerate(feedback):
            file = work/f'feedback{index}.txt'
            # RAM copies are installed together above, rather than enlarged in
            # whichever order the upstream reader encounters source hints.
            file.write_text(re.sub(r' rom=0x[0-9a-fA-F]{8}(?: size=0x[0-9a-fA-F]{1,8})?', '', content), encoding='utf-8')
            command.extend(['--miss-log', file])
        output = _run(command, work,
                      'Discover and translate ARM/Thumb code')
        if game:
            output=output.replace('it stays in the interpreter',
                'it is untranslated and will stop the native player if executed')
        count = re.search(r'anygba-recomp: (\d+) functions written', output)
        if count is None or int(count[1]) == 0:
            raise pc.PCError('GBA translator emitted no function coverage report')
        for source in (work/'generated').iterdir():
            if source.suffix in ('.c', '.h'):
                # Both directories share the export's staging filesystem. Move
                # generated units so a large ROM does not require two complete
                # copies of its translated source before atomic publication.
                source.replace(root/'game'/source.name)
        overlay_profile={**profile,'entries':[*profile.get('entries',[]),*automatic_entries]}
        instruction_regions=[r for r in automatic if r.get('instruction_fragments')]
        overlay_count = _overlays(emitter, path, work, root, copies, overlay_profile, feedback,instruction_regions)
        bios_stats=None
        if bios is not None:
            bios_stats=json.loads(_run([_emitter_tool(emitter,'gba-bios'),bios,root/'game'],work,
                'Translate supplied BIOS vectors and instruction entries'))
            if bios_stats['sha256']!=bios_identity['sha256']:raise pc.PCError('GBA BIOS changed during source generation')
        else:
            (root/'game/bios_dispatch.c').write_text('#include <anygba/bios_native.h>\n'
                'const anygba_bios anygba_compiled_bios={0,0,0,0,0,0};\n',encoding='utf-8')
    _fragment_dispatch(root)
    _runtime(sdk, root/'runtime/anygba')
    (root/'game/source_counts.h').write_text('#pragma once\n#define GBA_GENERATED_FUNCTIONS '+str(int(count[1])+overlay_count)+'u\n',encoding='utf-8')
    for source, dest in (('Project.cmake', 'CMakeLists.txt'), ('main.cpp', 'native/main.cpp'),
                         ('cheats.hpp', 'native/cheats.hpp'), ('cheats.cpp', 'native/cheats.cpp'),
                         ('settings_win32.cpp', 'native/settings_win32.cpp'),
                         ('customization.hpp', 'native/customization.hpp'),
                         ('customization.cpp', 'native/customization.cpp'),
                         ('cheat_tests.cpp', 'tests/cheats.cpp'),
                         ('tomlplusplus-license.txt', 'licenses/tomlplusplus.txt'),
                         ('video.hpp', 'native/video.hpp'), ('video.cpp', 'native/video.cpp'),
                         ('ppu.frag', 'native/ppu.frag'), ('shader.hpp.in', 'native/shader.hpp.in'),
                         ('graphics_tests.cpp', 'tests/graphics.cpp'),
                         ('cartridge_tests.cpp', 'tests/cartridge.cpp'),
                         ('native_idle.hpp', 'tests/native_idle.hpp'),
                         ('ram_feedback.hpp', 'native/ram_feedback.hpp'),
                         ('extract.py', 'tools/extract_assets.py')):
        content = _source(source)
        if source == 'Project.cmake' and game:
            content = content.replace('project(GbaNativeProbe', 'project(GbaNativeGame').replace(
                'gba_pc EXCLUDE_FROM_ALL', 'gba_pc').replace(
                'raw-state OpenGL rendering\" OFF)', 'raw-state OpenGL rendering\" ON)').replace(
                'set(GBA_DEFAULT_RENDERER \"auto\")', 'set(GBA_DEFAULT_RENDERER '+json.dumps(display['renderer'])+')')
            content=content.replace('explicit interpreter/reference probe\" ON)',
                'explicit interpreter/reference probe\" OFF)')
        (root/dest).parent.mkdir(parents=True, exist_ok=True)
        (root/dest).write_text(content, encoding='utf-8')
    (root/'assets.json').write_text(json.dumps(original, indent=2)+'\n', encoding='utf-8')
    (root/'analysis.json').write_text(json.dumps(dict(profile=profile, functions=int(count[1])+overlay_count,
        diagnostics=output, save_type=save_type, rtc=rtc, feedback=[pin for _, pin in feedback],
        inferred_ram_code=inferred, automatic_ram_code=automatic,automatic_ram_entries=automatic_entries,
        automatic_rom_entries=automatic_rom_entries,independent_ram_code=copies,
        automatic_instruction_regions=instruction_regions,
        guarded_ram_functions=overlay_count,compiled_bios=bios_stats), indent=2)+'\n', encoding='utf-8')
    (root/'.gitignore').write_text('/build*/\n/assets/\n*.sav\n*.sav.*\n*.ppm\n*.pcm\n', encoding='utf-8')
    (root/'README.md').write_text('''# GBA native translation probe

This independent C/C++ project runs statically translated cartridge code against a
source-shipped AnyGBA hardware core (MIT). It is a development probe, not a qualified
PC game port. Firmware is never fetched automatically. An explicitly supplied BIOS
can be translated with the cartridge. GPU presentation is still pending;
the internal reference PPU rasterizes at 240×160 on the CPU. No remake assets are needed.

```sh
python tools/extract_assets.py /path/to/your/game.gba
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel 2
./build/gba_probe --rom assets/game.gba --frames 8 --strict-static
```

On Visual Studio builds run `build/Release/gba_probe.exe`. The probe is headless:
`--help` lists RAM observations, image/PCM capture, held buttons and raw cartridge saves.
Interpreter fallback is disclosed in JSON and can be forbidden with `--strict-static`.
`--interpreter` selects the reference CPU for differential testing. Unsupported BIOS
services fail explicitly. A successful bounded run does not establish retail gameplay.
The original source project's `analysis.json` records discovered function count and notes.
Use `--miss-log NEW_FILE` to record input-bound coverage feedback. Re-export to a new
source folder with `decomp pc gba-probe ... --feedback NEW_FILE --experimental` to
translate newly observed callbacks and RAM code; then build and measure again.
Keep ROM-derived source private unless you have the necessary rights to share it.
''', encoding='utf-8')
    if game:
        (root/'README.md').write_text(_game_readme(), encoding='utf-8')
    if bios_identity:
        with (root/'README.md').open('a',encoding='utf-8') as readme:
            readme.write('''
## Translated owner firmware

This export includes native C and initial data derived from the BIOS explicitly
supplied at generation. Keep that firmware-derived output private alongside the
game-derived code. The compiled image is selected automatically; no separate
runtime BIOS file is required. `--strict-static` permits the exact translated
image and rejects a mismatched replacement. The reference `--interpreter` mode
uses the same initial BIOS bytes for comparison. JSON exposes
`bios_native_dispatches` and `interpreted_cycles` separately.
''')
    if inspect(path)['input'] != original:
        raise pc.PCError('GBA owner input changed during source generation')
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file()}
    manifest = dict(schema=pc.SCHEMA, platform='gba', output_kind='game' if game else 'cpu-probe',
        backend=dict(id=GAME_BACKEND_ID if game else BACKEND_ID, revision=revision()), execution_model='static-recompiled' if game else 'hybrid',
        runtime=dict(id='anygba-core', revision=SDK_COMMIT, license='MIT'), inputs=[original,*([bios_identity] if bios_identity else [])],
        build=dict(system='cmake', target='gba_pc' if game else 'gba_probe'), files=files,
        fallback=dict(interpreter=not game, runtime_compilation=False),
        qualification=dict(graphics=False, retail=False, host_build=False),
        code_generation=dict(functions=int(count[1])))
    manifest['firmware']=dict(mode='compiled' if bios is not None else 'hle' if game else 'hle-or-explicit-interpreter',
        sha256=bios_identity['sha256'] if bios_identity else None,code_generation=bios_stats)
    if game:
        manifest['reference_tools']=dict(target='gba_probe',cmake_option='GBA_BUILD_REFERENCE',
            built_by_default=False,execution_model='hybrid',interpreter=True)
    if game:
        manifest['presentation'] = display
    (root/'pc-project.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


def backend():
    return pc.Backend(BACKEND_ID, 'gba', revision(), generate, experimental=True)


def export(rom, destination, *, profile=None, save_type='auto', rtc='auto', feedback=(), bios=None, log=None):
    token = _progress.set(log)
    try:
        return pc.export_backend(dict(platform='gba', input=str(rom), profile=profile,
            save_type=save_type, rtc=rtc, feedback=feedback or (),bios=bios), Path(destination), backend())
    finally:
        _progress.reset(token)


def game_backend():
    return pc.Backend(GAME_BACKEND_ID, 'gba', revision(), generate_game, experimental=True)


def generate_game(project, root):
    generate({**project, 'output_kind': 'game'}, root)


def export_game(rom, destination, *, profile=None, save_type='auto', rtc='auto', feedback=(), bios=None, renderer='auto', log=None):
    token = _progress.set(log)
    try:
        return pc.export_backend(dict(platform='gba', input=str(rom), profile=profile,
            output_kind='game', renderer=renderer, save_type=save_type, rtc=rtc,
            feedback=feedback or (),bios=bios), Path(destination), game_backend())
    finally:
        _progress.reset(token)


def _game_readme():
    return """# GBA native PC source project

This independent, editable C/C++ repository contains translated ARM/Thumb cartridge
code in `game/`, a source-shipped AnyGBA hardware runtime (MIT) and an SDL/OpenGL
frontend. No decomp.wtf installation, agent, emulator process, ROM or Nintendo BIOS
is included. Extract your own exact cartridge once; no mobile/remake assets are needed.

```sh
python tools/extract_assets.py /path/to/your/game.gba
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel 2
./build/gba_pc
```

On Visual Studio use `build/Release/gba_pc.exe`. Build tools: CMake 3.20+ and a
C++20 compiler (Visual Studio C++ on Windows, GCC/Clang on Linux). CMake downloads
the pinned SDL 3.4.10 source automatically unless an installed SDL3 is available.
On Linux install your distribution's X11/Wayland, OpenGL and audio development
packages before configuring SDL. OpenGL 3.3 and an audio device are runtime needs.

The initial window adapts to the active monitor; resize it or press F11 for native
monitor fullscreen. Aspect ratio is preserved. OpenGL renders raw GBA tile, sprite,
palette and scanline state at the drawable resolution; it does not upload the CPU
reference picture. Cartridge art retains its original pixel detail. `--renderer
opengl` requires that path; `auto` reports any software fallback on stderr and in
the exit report. A software OpenGL driver may be selected by the operating system;
the report names the actual device. `--renderer software` selects CPU compatibility.

Controls: arrows, X (A), Z (B), Enter (Start), Backspace (Select), Q (L), W (R).
Gamepads use the directional pad, south/east buttons, Start/Back and shoulders.
Stereo sound plays at 32768 Hz. Raw cartridge saves persist atomically under
`saves/<input-hash>.sav`; `--save PATH` imports/reuses your raw save. The original
cartridge's save chip and RTC are detected automatically; generation options can
override unusual cartridges. Close the window to flush saves.

This is experimental static recompilation. The `gba_pc` player contains neither an
instruction interpreter nor a runtime compiler. Missing code stops with a coverage
diagnostic instead of silently changing execution methods. `analysis.json` records
discovered functions and independently guarded RAM variants. Multiple code copies
may overlap or reuse one address. Position-independent routines can also execute
from changing stack addresses; dispatch checks their complete original bytes.
A bounded passing test does not establish complete retail compatibility.

Most games use the built-in BIOS services. For games requiring original firmware,
including its sound driver, supply your own 16 KiB BIOS to the exporter with
`--bios /path/to/your/gba-bios.bin`. It emits native firmware code and initial data
that are selected automatically at runtime. Keep those derived files private.
The player rejects an untranslated replacement BIOS. No BIOS is downloaded. The
BIOS-free MultiBoot service returns a disconnected-cable failure; link play is not
implemented.

For differential validation or coverage investigation, configure the optional
`-DGBA_BUILD_REFERENCE=ON` target and build `gba_probe`. Only that separate probe
contains an interpreter: `--interpreter` selects the reference CPU, and
`--miss-log NEW_FILE` records uncovered code during hybrid execution. Re-export with
`decomp pc gba-native ... --feedback NEW_FILE --experimental` into a new source
folder. Feedback binds to the cartridge hash and preserves existing project edits.
`--frames N --unpaced --input-script FILE --capture reference.ppm
--display-capture gpu.ppm --audio-pcm audio.pcm` supports repeatable bounded checks.
Input script lines are `frame pressed-mask`, with increasing frames and a ten-bit
GBA button mask (A=1, B=2, Select=4, Start=8, Right=16, Left=32, Up=64, Down=128,
R=256, L=512). Masks remain held until the next line.

Original graphics conformance tests are included: configure with
`-DGBA_BUILD_GPU_TESTS=ON`, build `gba_gpu_tests` and run it on an OpenGL desktop.
These compare all six PPU modes, sprites, effects and resizing against the internal
reference, using an unrelated CPU picture as GPU input to detect framebuffer blits.
Keep cartridge-derived source, assets and save files private unless you have the
necessary rights to share them.

## Cheat codes and settings

On Windows, F1 or Escape opens the native settings window and pauses the game.
Add a named code, choose auto-detect or its device format, enable/disable entries,
then choose Save and close. F12 is the cheat device button. The window also opens
the save folder. Preferences are stored beside the cartridge save as
`<save-name>.sav.cheats.toml`; they are separate from raw cartridge save bytes.

Every host also accepts `--cheat "cb:82000200 1234"` or `--cheats FILE` for one
run. Formats: `auto`, `arv3`, `gsv1`, `cb`, `raw`, `arv3raw`, `gsv1raw`.
The pinned SDK decodes encrypted Action Replay v3 and GameShark v1/v2, CodeBreaker,
conditions, pointer writes and its raw pointer/XOR extensions. Encrypted CodeBreaker
has only deterministic upstream checks; real-device compatibility is unverified.
Unsupported formats and DEADFACE reseeding produce errors. Master/hook codes are
accepted as no-ops because enabled programs already run once each frame.

Live ROM patches are rejected: this native-only player cannot use the SDK's
interpreter-backed instruction-patch path. A cheat that changes cartridge code or
folded literals requires a native source customization. RAM-code replacement can
also invalidate a compiled body and stop with a coverage diagnostic.

Example preference file (disabled until enabled by the user):

```toml
[[cheat]]
name = "Example RAM write"
format = "cb"
code = ["82000200 1234"]
enabled = false
```

Raw saves retain the original cartridge format. Close the game before editing a
save in an external editor, then reopen and load it. No wrapper or cheat metadata
is inserted into `.sav` files.
Third-party notices include `runtime/anygba/LICENSE` and
`licenses/tomlplusplus.txt`; include them with distributed builds.

## Project customizations

Optional `custom/game.cpp` implements `gba_customization::configure(System&)` and
`gba_customization::description()` from `native/customization.hpp`. CMake uses it
instead of the empty default; JSON reports `game_customized: true`. Keep optional
invariant tests in `custom/tests.cpp` (the `gba_custom_tests` target).

Generated-file integrity covers the baseline listed in `pc-project.json`.
Record custom source hashes and validation separately. Re-export into a fresh
folder, preserve these project-owned files, and test the combined build before
publishing a customized game.
"""
