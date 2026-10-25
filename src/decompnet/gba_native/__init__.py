"""Standalone GBA C/C++ projects with raw-state GPU rendering and explicit fallback."""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
from importlib import resources
import json
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
RUNTIME_DIRS = ('apu', 'ppu', 'bios', 'save', 'state', 'interp')
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
                 'video.hpp', 'video.cpp', 'ppu.frag', 'shader.hpp.in', 'graphics_tests.cpp', 'cartridge_tests.cpp'):
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


def _run(command, cwd, what):
    _log(what+'...')
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
    work = sdk.parent/'.gba-emitter'/revision()[:16]
    work.mkdir(parents=True, exist_ok=True)
    identity = dict(commit=SDK_COMMIT, sha256=_fingerprint(sdk))
    marker = work/'source.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) != identity:
        raise pc.PCError('GBA cached sources changed; preserve edits and choose a clean toolchain cache')
    (work/'CMakeLists.txt').write_text(_source('Emitter.cmake'), encoding='utf-8')
    _run(['cmake', '-S', work, '-B', work/'build', '-DGBA_SDK='+sdk.as_posix(),
          '-DCMAKE_BUILD_TYPE=Release'], work, 'Configure GBA static translator')
    _run(['cmake', '--build', work/'build', '--target', 'anygba-recomp', '--config', 'Release',
          '--parallel', '2'], work, 'Build GBA static translator')
    marker.write_text(json.dumps(identity)+'\n', encoding='utf-8')
    executable = next((p for p in (work/'build/recomp/anygba-recomp',
        work/'build/recomp/Release/anygba-recomp.exe', work/'build/recomp/anygba-recomp.exe') if p.is_file()), None)
    if executable is None:
        raise pc.PCError('GBA static translator was not built')
    return executable


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
        if any(address < end and address+length > begin for begin, end in ranges):
            raise pc.PCError('overlapping GBA RAM code needs a reviewed overlay implementation')
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
        match = re.fullmatch(r'(0x[0-9a-fA-F]{8}) (arm|thumb)(?: rom=(0x[0-9a-fA-F]{8}))?', line)
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
                sources = hints.setdefault(address, set())
                if len(fields) == 3:
                    sources.add((int(fields[2][4:], 16), fields[1]))
    reviewed = profile.get('ram_code', [])
    boundaries = sorted({*hints, *[r['address'] for r in reviewed], 0x02040000, 0x03008000})
    regions = []
    for index, address in enumerate(boundaries):
        if address not in hints or len(hints[address]) != 1:
            continue
        if any(r['address'] <= address < r['address']+r['size'] for r in reviewed):
            continue
        source, mode = next(iter(hints[address]))
        end = min(boundaries[index+1], 0x02040000 if address < 0x03000000 else 0x03008000)
        width = 4 if mode == 'arm' else 2
        length = min(end-address, 0x08000000+size-source)//width*width
        if length:
            # A function can cross an interior observed entry. Keep contiguous
            # bytes from the same ROM copy together so its whole-body byte guard
            # can resolve one original source span.
            if (regions and regions[-1]['address']+regions[-1]['size'] == address and
                regions[-1]['rom']+regions[-1]['size'] == source and regions[-1]['mode'] == mode):
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
    header.write_text(text.replace(old, old+'\n    bool strict_static = false;'), encoding='utf-8')
    dispatch = destination/'runtime/src/dispatch.cpp'
    text = dispatch.read_text(encoding='utf-8')
    old = 'void System::interpret() {'
    if text.count(old) != 1:
        raise pc.PCError('GBA interpreter guard patch no longer applies')
    dispatch.write_text(text.replace(old, old+'\n    if (options_.strict_static) {\n'
        '        fail("static coverage miss at " + std::to_string(cpu_.r[15]));\n    }'), encoding='utf-8')
    text = dispatch.read_text(encoding='utf-8')
    old = 'options_.log_misses = false;\n            return;'
    if text.count(old) != 1:
        raise pc.PCError('GBA feedback error patch no longer applies')
    text = text.replace(old, 'fail("cannot append GBA coverage feedback");')
    old = '    std::fflush(miss_file_);'
    if text.count(old) != 1:
        raise pc.PCError('GBA feedback flush patch no longer applies')
    dispatch.write_text(text.replace(old,
        '    if (std::fflush(miss_file_) != 0 || std::ferror(miss_file_)) fail("GBA coverage feedback write failed");'), encoding='utf-8')
    bios = destination/'runtime/src/bios/swi_table.cpp'
    text = bios.read_text(encoding='utf-8')
    old = 'void System::stub_swi(std::uint32_t number, std::uint32_t call_pc) {'
    if text.count(old) != 1:
        raise pc.PCError('GBA BIOS guard patch no longer applies')
    bios.write_text(text.replace(old, old+'\n    fail("unsupported GBA BIOS service " + std::to_string(number) +'
        ' " at " + std::to_string(call_pc));'), encoding='utf-8')
    (destination/'DECOMP_WTF_PATCHES.md').write_text(
        'Pinned AnyGBA '+SDK_COMMIT+' (MIT).\n\n'
        'This source-shipped core omits the upstream player, network control, cheats and HD packs. '
        'Options.strict_static rejects interpreter execution. Explicit coverage feedback fails on write errors. Unsupported BIOS sound/link '
        'services stop with a diagnostic instead of being ignored. The independent desktop frontend renders raw scanline state with OpenGL.\n', encoding='utf-8')


def generate(project, root):
    path = Path(project['input']).resolve()
    inspection = inspect(path)
    original = inspection['input']
    profile = _profile(project.get('profile'), original['sha256'])
    _regions(profile, original['size'])
    feedback = [_feedback(p, original['sha256'], original['size']) for p in project.get('feedback', [])]
    inferred = _feedback_regions(profile, feedback, original['size'])
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
        config = '[game]\ntitle = '+json.dumps(inspection['title'])+'\n'
        if save_type != 'auto':
            config += 'save = '+json.dumps(save_type)+'\n'
        if rtc != 'auto':
            config += 'rtc = '+('true' if rtc == 'on' else 'false')+'\n'
        for row in profile.get('entries', []):
            config += f'\n[[entry]]\naddr = {row["address"]}\nmode = "{row["mode"]}"\n'
        for row in [*profile.get('ram_code', []), *inferred]:
            config += f'\n[[ram_region]]\nrom_src = {row["rom"]}\nram_dst = {row["address"]}\nsize = {row["size"]}\nmode = "{row["mode"]}"\n'
        cfg = work/'game.toml'; cfg.write_text(config, encoding='utf-8')
        command = [emitter, path, '--config', cfg, '--output', work/'generated']
        for index, (content, _) in enumerate(feedback):
            file = work/f'feedback{index}.txt'
            # RAM copies are installed together above, rather than enlarged in
            # whichever order the upstream reader encounters source hints.
            file.write_text(re.sub(r' rom=0x[0-9a-fA-F]{8}', '', content), encoding='utf-8')
            command.extend(['--miss-log', file])
        output = _run(command, work,
                      'Discover and translate ARM/Thumb code')
        count = re.search(r'anygba-recomp: (\d+) functions written', output)
        if count is None or int(count[1]) == 0:
            raise pc.PCError('GBA translator emitted no function coverage report')
        for source in (work/'generated').iterdir():
            if source.suffix in ('.c', '.h'):
                shutil.copyfile(source, root/'game'/source.name)
    _runtime(sdk, root/'runtime/anygba')
    for source, dest in (('Project.cmake', 'CMakeLists.txt'), ('main.cpp', 'native/main.cpp'),
                         ('video.hpp', 'native/video.hpp'), ('video.cpp', 'native/video.cpp'),
                         ('ppu.frag', 'native/ppu.frag'), ('shader.hpp.in', 'native/shader.hpp.in'),
                         ('graphics_tests.cpp', 'tests/graphics.cpp'),
                         ('cartridge_tests.cpp', 'tests/cartridge.cpp'),
                         ('extract.py', 'tools/extract_assets.py')):
        content = _source(source)
        if source == 'Project.cmake' and game:
            content = content.replace('project(GbaNativeProbe', 'project(GbaNativeGame').replace(
                'gba_pc EXCLUDE_FROM_ALL', 'gba_pc').replace(
                'raw-state OpenGL rendering\" OFF)', 'raw-state OpenGL rendering\" ON)').replace(
                'set(GBA_DEFAULT_RENDERER \"auto\")', 'set(GBA_DEFAULT_RENDERER '+json.dumps(display['renderer'])+')')
        (root/dest).write_text(content, encoding='utf-8')
    (root/'assets.json').write_text(json.dumps(original, indent=2)+'\n', encoding='utf-8')
    (root/'analysis.json').write_text(json.dumps(dict(profile=profile, functions=int(count[1]),
        diagnostics=output, save_type=save_type, rtc=rtc, feedback=[pin for _, pin in feedback],
        inferred_ram_code=inferred), indent=2)+'\n', encoding='utf-8')
    (root/'.gitignore').write_text('/build*/\n/assets/\n*.sav\n*.sav.*\n*.ppm\n*.pcm\n', encoding='utf-8')
    (root/'README.md').write_text('''# GBA native translation probe

This independent C/C++ project runs statically translated cartridge code against a
source-shipped AnyGBA hardware core (MIT). It is a development probe, not a qualified
PC game port. No ROM or Nintendo BIOS is included. GPU presentation is still pending;
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
    if inspect(path)['input'] != original:
        raise pc.PCError('GBA owner input changed during source generation')
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file()}
    manifest = dict(schema=pc.SCHEMA, platform='gba', output_kind='game' if game else 'cpu-probe',
        backend=dict(id=GAME_BACKEND_ID if game else BACKEND_ID, revision=revision()), execution_model='hybrid',
        runtime=dict(id='anygba-core', revision=SDK_COMMIT, license='MIT'), inputs=[original],
        build=dict(system='cmake', target='gba_pc' if game else 'gba_probe'), files=files,
        fallback=dict(interpreter=True, runtime_compilation=False),
        qualification=dict(graphics=False, retail=False, host_build=False),
        code_generation=dict(functions=int(count[1])))
    if game:
        manifest['presentation'] = display
    (root/'pc-project.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


def backend():
    return pc.Backend(BACKEND_ID, 'gba', revision(), generate, experimental=True)


def export(rom, destination, *, profile=None, save_type='auto', rtc='auto', feedback=(), log=None):
    token = _progress.set(log)
    try:
        return pc.export_backend(dict(platform='gba', input=str(rom), profile=profile,
            save_type=save_type, rtc=rtc, feedback=feedback or ()), Path(destination), backend())
    finally:
        _progress.reset(token)


def game_backend():
    return pc.Backend(GAME_BACKEND_ID, 'gba', revision(), generate_game, experimental=True)


def generate_game(project, root):
    generate({**project, 'output_kind': 'game'}, root)


def export_game(rom, destination, *, profile=None, save_type='auto', rtc='auto', feedback=(), renderer='auto', log=None):
    token = _progress.set(log)
    try:
        return pc.export_backend(dict(platform='gba', input=str(rom), profile=profile,
            output_kind='game', renderer=renderer, save_type=save_type, rtc=rtc,
            feedback=feedback or ()), Path(destination), game_backend())
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

This is experimental hybrid static recompilation. Discovered functions are C;
uncovered callbacks and modified RAM code use the shipped interpreter, with exact
misses disclosed. No runtime compiler is used. `--strict-static` stops on a miss;
`--interpreter` selects the CPU reference for differential testing. Unsupported BIOS
services stop with diagnostics. `analysis.json` records the discovered functions.
A bounded passing test does not establish complete retail compatibility.

For coverage, run `--miss-log NEW_FILE`, then re-export with `decomp pc gba-native
... --feedback NEW_FILE --experimental` into a new source folder. This binds feedback
to the cartridge hash and adds observed code without discarding existing edits.
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
"""
