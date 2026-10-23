"""Mixed compiler profiles, module-aware rooms and recompressed function growth."""

import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile
from starlette.testclient import TestClient

from decompnet import compiler, elfobj, project, toolchains
from decompnet.app import collab
from decompnet.app.engine import RomNetwork
from decompnet.cli import main
from decompnet.network import NetworkError
from decompnet.rom import n64_layout
from decompnet.rom.n64_crc import calculate
from .test_n64_shiftable import fixture as resident_fixture
from .test_n64code import _code


def run(tree, *arguments):
    return subprocess.run([sys.executable, 'build.py', *arguments], cwd=tree, capture_output=True, text=True)


def profile_fixture(tmp_path):
    image = bytearray(0x200000)
    image[:16] = struct.pack('>4I', 0x80371240, 15, 0x80000400, 0)
    image[0x20:0x34] = b'MIXED PROFILE TEST'.ljust(20, b' ')
    modules, functions = [], []
    # Different original compilers/flags share one cartridge. Two modules also
    # share RAM, so addresses alone cannot identify their work or settings.
    for index, (name, level, frontend, language) in enumerate([
            ('main', '-O2', 'edg', 'c++'), ('battle', '-O0', 'edg', 'c++'),
            ('field', '-O2', 'cfront', 'c++'), ('menu', '-O2', 'edg', 'c')]):
        flags = [level, *[f for f in toolchains.get('ido-5.3').flags if not f.startswith('-O')]]
        cfg = {'kind': 'rom', 'platform': 'n64', 'compiler': {'toolchain': 'ido-5.3',
               'flags': flags, 'sandbox': 'none', 'language': language, 'cpp_frontend': frontend}}
        source = f'int probe(int value) {{ return value + {index + 1}; }}\n'
        if level == '-O0':
            source = 'void probe(int unused) {}\n'
        result = compiler.compile_source(project.compiler_config(tmp_path, cfg), '', source)
        assert result.ok, result.log
        obj = elfobj.extract_function(result.obj, 'probe')
        assert not obj.relocs
        start, vram = 0x1000 + index * 0x10000, 0x80000400 if index == 0 else 0x80400000
        code = obj.code + _code(vram + len(obj.code), 40)
        image[start:start + len(code)] = code
        image[start + len(code):start + len(code) + 16] = struct.pack('>4I', index + 100, 7, 3, 4)
        module = {'name': name, 'rom_start': start, 'rom_end': start + len(code) + 16, 'vram': vram,
                  'sections': [{'offset': 0, 'type': 'code'}, {'offset': len(code), 'type': 'data'}]}
        if index:
            module['exclusive_group'] = 'scenes'
        modules.append(module)
        functions.append({'module': name, 'vram': vram, 'data_vram': vram + len(code), 'level': level, 'source': source,
                          'profile': {'toolchain': 'ido-5.3', 'flags': flags, 'language': language,
                                      'cpp_frontend': frontend}})
    struct.pack_into('>2I', image, 0x10, *calculate(image, 6102))
    return bytes(image), {'format': 1, 'sha256': hashlib.sha256(image).hexdigest(), 'modules': modules}, functions


def imported_profiles(tmp_path):
    original, layout, functions = profile_fixture(tmp_path)
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, toolchain='ido-5.3', confirmed=True, log=lambda *_: None)
    for function in functions:
        row = next(r for r in net.store.all('SELECT * FROM functions WHERE project_id=? AND vram=?', net.project_row(slug)['id'], function['vram'])
                   if r['unit'] == function['module'])
        function['name'] = row['name']
        function['source'] = function['source'].replace('probe', row['name'])
        net.set_function_compiler(slug, row['name'], function['profile'])
    return net, slug, original, layout, functions


def test_mixed_profiles_match_regress_and_clean_export_in_one_project(tmp_path):
    net, slug, original, layout, functions = imported_profiles(tmp_path)
    agent, _ = net.local_agent('profile-test')
    for function in functions:
        result = net.attempt(agent, function['name'], function['source'], slug)
        assert result['matched'], result['text']
        detail = net.function_detail(slug, function['name'])
        assert detail['compiler']['flags'][0] == function['level']
        assert detail['language'] == function['profile']['language']
    config = net.cfg(net.project_row(slug))
    assert 'frontend: cfront' in net.get_function(functions[2]['name'], slug)
    changed = copy.deepcopy(functions[1]['profile'])
    changed['flags'][0] = '-O2'
    with pytest.raises(NetworkError, match='invalidate a saved match'):
        net.set_function_compiler(slug, functions[1]['name'], changed)
    assert net.cfg(net.project_row(slug))['function_compilers'] == config['function_compilers']
    assert not net.regression_test(net.project_row(slug), net._context(net.project_row(slug)['id'])['header'])
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'] and result['matched'] == 4 and result['fallback'] == [], result
    tree = Path(result['path'])
    metadata = json.loads((tree / 'build.json').read_text())
    for function in functions:
        entry = next(f for f in metadata['functions'] if f['name'] == function['name'])
        assert entry['compiler'] == function['profile']
        assert entry['source'].endswith('.c' if function['profile']['language'] == 'c' else '.cpp')
    for generated in ('asm', 'assets', 'build'):
        shutil.rmtree(tree / generated)
    process = run(tree)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tree / 'build/game.z64').read_bytes() == original
    # The console command can reset an open function and select another period
    # frontend without changing the settings of its neighbours.
    open_fn = net.store.one("SELECT name FROM functions WHERE project_id=? AND status='open'", net.project_row(slug)['id'])['name']
    args = ['--db', str(tmp_path / 'app.db'), 'n64', 'profile', slug, open_fn, '--workspace', str(tmp_path / 'projects')]
    assert main([*args, '--optimization', 'O0', '--frontend', 'cfront']) == 0
    assert net.cfg(net.project_row(slug))['function_compilers'][open_fn]['cpp_frontend'] == 'cfront'
    assert main([*args, '--reset']) == 0
    assert open_fn not in net.cfg(net.project_row(slug))['function_compilers']


def test_reviewed_rooms_keep_overlapping_matches_notes_profiles_and_renames_separate(tmp_path):
    host, slug, original, layout, functions = imported_profiles(tmp_path)
    room = host.rooms[slug] = collab.Room(host, slug)
    code = room.open_invite()
    client = TestClient(collab.host_app(host, host.rooms), base_url='https://fixture.invalid')
    guest = RomNetwork(tmp_path / 'guest.db', tmp_path / 'guest')
    link = f'https://fixture.invalid/join/{code}#room={slug}'
    gslug = collab.join_room(guest, link, 'friend', original, client=client, start=False, log=lambda *_: None)
    connection = guest.links[gslug]
    connection.sync()
    assert guest.cfg(guest.project_row(gslug))['n64_layout'] == host.cfg(host.project_row(slug))['n64_layout']
    assert guest.cfg(guest.project_row(gslug))['function_compilers'] == host.cfg(host.project_row(slug))['function_compilers']
    battle, field = functions[1:3]
    ha, _ = host.local_agent('host-agent')
    ga, _ = guest.local_agent('guest-agent')
    assert 'CLAIMED' in guest.claim(ga, gslug, battle['name'])
    assert 'CLAIMED' in host.claim(ha, slug, field['name'])
    assert guest.attempt(ga, battle['name'], battle['source'], gslug)['matched']
    connection.sync()
    assert guest._function(battle['name'], gslug)['status'] == 'matched'
    assert guest._function(field['name'], gslug)['status'] == 'open'
    host.add_note(ha, slug, 'field module only', field['name'])
    connection.sync()
    note = guest.store.one("SELECT function_id FROM notes WHERE text='field module only'")
    assert note['function_id'] == guest._function(field['name'], gslug)['id']
    assert host.attempt(ha, field['name'], field['source'], slug)['matched']
    assert host.rename_symbol(ha, slug, battle['name'], 'battle_update').startswith('✅')
    assert host.edit_context(ha, slug, '', 'typedef int field_counter;', 'field context', field['name']).startswith('✅')
    connection.sync()
    assert guest._function('battle_update', gslug)['status'] == 'matched'
    assert guest._function(field['name'], gslug)['status'] == 'matched'
    assert guest.cfg(guest.project_row(gslug))['function_compilers']['battle_update']['flags'][0] == '-O0'
    assert 'field_counter' in guest.get_context(gslug, field['name'])
    assert 'field_counter' not in guest.get_context(gslug, 'battle_update')
    definitions = []
    import re
    for path in (Path(host.project_row(slug)['root']) / 'asm/data').glob('**/*.s'):
        definitions.extend(re.findall(r'^dlabel (\w+)', path.read_text(), re.M))
    old = next(n for n in definitions if host.symbols(host.project_row(slug)['id']).resolve(n) == field['data_vram']
               and host._symbol_module(host.project_row(slug), n) == 'field')
    assert host.rename_symbol(ha, slug, old, 'field_tally').startswith('✅')
    connection.sync()
    assert guest.cfg(guest.project_row(gslug))['symbol_modules']['field_tally'] == 'field'
    exported = guest.export_rom(gslug, log=lambda *_: None)
    assert exported['identical'], exported
    symbols = json.loads((Path(exported['path']) / 'build.json').read_text())['module_symbols']
    assert 'field_tally' in symbols['field'] and 'field_tally' not in symbols['menu']
    # A split in one overlay at a reused address must leave the other intact.
    rows = host.store.all("SELECT * FROM functions WHERE project_id=? AND unit='battle' AND status='open' ORDER BY vram", host.project_row(slug)['id'])
    owner = rows[0]
    peer = next(r for r in host.store.all('SELECT * FROM functions WHERE project_id=? AND unit=?', host.project_row(slug)['id'], 'field')
                if r['vram'] <= owner['vram'] + 16 < r['vram'] + r['size'])
    host.set_function_compiler(slug, owner['name'], functions[1]['profile'])
    assert host.split_function(ha, slug, owner['name'], hex(owner['vram'] + 16), 'battle_tail').startswith('✅')
    connection.sync()
    assert guest._function('battle_tail', gslug)['unit'] == 'battle'
    assert guest.cfg(guest.project_row(gslug))['function_compilers']['battle_tail']['flags'][0] == '-O0'
    assert guest._function(peer['name'], gslug)['size'] == peer['size']
    state = room.state(0, 0, 0, None)
    assert 'glabel' not in json.dumps(state) and 'target' not in state
    with pytest.raises(NetworkError, match='layout or protocol'):
        connection.apply({**state, 'n64_layout': '0' * 64})
    assert collab.reconnect(guest, gslug, link, client=client, start=False, log=lambda *_: None) == gslug
    # A host profile change between local compile and confirmation cannot leave
    # a false local match. The source is retained as an attempt for retrying.
    main_function = functions[0]
    changed = copy.deepcopy(main_function['profile'])
    changed['flags'][0] = '-O0'
    host.set_function_compiler(slug, main_function['name'], changed)
    with pytest.raises(NetworkError, match='host did not confirm'):
        guest.attempt(ga, main_function['name'], main_function['source'], gslug)
    assert guest._function(main_function['name'], gslug)['status'] == 'open'
    assert guest._function(main_function['name'], gslug)['best_source'] == main_function['source']
    assert guest._function(main_function['name'], gslug)['best_score'] > 0
    assert guest.cfg(guest.project_row(gslug))['function_compilers'][main_function['name']]['flags'][0] == '-O0'


def growth_fixture(codec):
    original, layout = resident_fixture()
    image = bytearray(original)
    for index, (name, address) in enumerate([('resident', 0x80010400), ('battle', 0x80400000), ('field', 0x80400000)]):
        decoded = _code(address, 40) + bytes(768) + struct.pack('>4I', address + 32, 7 + index, 3, 4)
        start = 0x10000 * (index + 1)
        compression = codec if index else 'none'
        stored = decoded if compression == 'none' else n64_layout.encode(decoded, compression)
        image[start:start + len(stored)] = stored
        module = {'name': name, 'rom_start': start, 'rom_end': start + (len(decoded) if compression == 'none' else 0x4000),
                  'vram': address, 'text_end': 1280, 'sections': [{'offset': 0, 'type': 'code'}, {'offset': 0x800, 'type': 'data'}]}
        if index:
            module['exclusive_group'] = 'scenes'
        if compression != 'none':
            module.update(compression=compression, decoded_size=len(decoded))
        layout['modules'].append(module)
    # The unchanged first main function calls a function that will move in a
    # different resident module. This tests real external link resolution.
    struct.pack_into('>I', image, 0x1008, 0x0C000000 | ((0x80010420 >> 2) & 0x3FFFFFF))
    struct.pack_into('>2I', image, 0x10, *calculate(image, 6102))
    layout['sha256'] = hashlib.sha256(image).hexdigest()
    return bytes(image), layout


@pytest.mark.parametrize('codec', ['none', 'yaz0', 'deflate-1172', 'deflate-1173', 'gzip'])
def test_independent_module_growth_relinks_calls_pointers_and_recompresses(tmp_path, codec):
    original, layout = growth_fixture(codec)
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, toolchain='ido-5.3', confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, format='shiftable', log=lambda *_: None)
    assert result['identical'] and result['shiftable']['ready'], result
    tree = Path(result['path'])
    metadata = json.loads((tree / 'build.json').read_text())
    seconds = {}
    for name in ('resident', 'battle', 'field'):
        first, second, *_ = sorted((f for f in metadata['functions'] if f['seg'] == name), key=lambda f: f['vram'])
        seconds[name] = second
        source = tree / 'src' / name / (first['name'] + '.cpp')
        source.parent.mkdir(parents=True, exist_ok=True)
        count = {'resident': 8, 'battle': 10, 'field': 12}[name]
        source.write_text(f'extern "C" int {second["name"]}(int);\nextern "C" int {first["name"]}(int value) {{\n'
            f'volatile int values[{count}];\n' + ''.join(f'values[{i}] = value + {i};\n' for i in range(count)) +
            f'return {second["name"]}(value)' + ''.join(f' + values[{i}]' for i in range(count)) + '; }\n')
    if codec == 'none':
        # A shared assembler alias has a different final address in each
        # alternative program. Keep its binding local to that module's ELF.
        alias = '.L80400020'
        for path in (tree / 'asm/data').glob('**/*.s'):
            text = path.read_text()
            for name in ('battle', 'field'):
                text = text.replace(seconds[name]['name'], alias)
            path.write_text(text)
    process = run(tree, 'mod')
    assert process.returncode == 0, process.stdout + process.stderr
    changed = (tree / 'build/mod.z64').read_bytes()
    report = json.loads((tree / 'build/shiftable-result.json').read_text())
    assert len(changed) == len(original) and changed != original
    assert len(report['modules']) == 4
    for item in report['modules']:
        assert item['used_growth'] <= item['available_growth']
    # The original JAL in main now reaches the new address in resident's ELF.
    assert 0x80000000 | ((int.from_bytes(changed[0x1008:0x100C], 'big') & 0x3FFFFFF) << 2) == report['functions'][seconds['resident']['name']]
    for name, second in seconds.items():
        assert report['functions'][second['name']] > second['vram']
        with (tree / f'build/modules/{name}.elf').open('rb') as stream:
            elf = ELFFile(stream)
            data = elf.get_section_by_name('.' + name).data()
            symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        assert int.from_bytes(data[0x800:0x804], 'big') == symbols[second['name']] == report['functions'][second['name']]
        assert data[0x804:0x810] == struct.pack('>3I', 7 + ('resident', 'battle', 'field').index(name), 3, 4)
        if codec != 'none' and name != 'resident':
            block = next(b for b in metadata['container']['layout']['blocks'] if b['working_start'] == next(
                s['start'] for s in metadata['segments'] if s['name'] == name))
            assert n64_layout.decode(changed, block, verify=False) == data
    assert len(report['recompressed']) == (0 if codec == 'none' else 2)
    assert struct.unpack_from('>2I', changed, 0x10) == calculate(changed, 6102)
    for generated in ('asm', 'assets', 'build'):
        shutil.rmtree(tree / generated)
    clean = run(tree, 'mod')
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert (tree / 'build/mod.z64').read_bytes() == changed
    assert run(tree).returncode != 0
    if codec != 'none':
        limits = copy.deepcopy(metadata)
        for block in limits['container']['layout']['blocks']:
            decoded = n64_layout.decode(original, block)
            block['end'] = block['offset'] + len(n64_layout.encode(decoded, codec))
        (tree / 'build.json').write_text(json.dumps(limits))
        failed = run(tree, 'mod')
        assert failed.returncode != 0 and 'storage reserve' in failed.stderr, failed.stdout + failed.stderr
        assert not (tree / 'build/mod.z64').exists()


@pytest.mark.parametrize('codec', ['yaz0', 'deflate-1172', 'deflate-1173', 'gzip'])
def test_recompression_roundtrips_independently_and_rejects_storage_overflow(codec):
    original, layout = growth_fixture(codec)
    segments, working, metadata = n64_layout.reviewed(original, layout)
    assert n64_layout.repack(original, metadata, working) == (original, [])
    block = metadata['blocks'][0]
    data = random.Random(1234).randbytes(block['size'])
    encoded = n64_layout.encode(data, codec)
    # Native Yaz0 and zlib decode independently of the encoder's match search.
    assert n64_layout.decode(encoded, {'codec': codec, 'offset': 0, 'end': len(encoded), 'size': len(data)}, verify=False) == data
    changed = bytearray(working)
    changed[block['working_start']:block['working_start'] + block['size']] = data
    rebuilt, records = n64_layout.repack(original, metadata, changed)
    assert n64_layout.decode(rebuilt, block, verify=False) == data and records
    small = copy.deepcopy(metadata)
    small['blocks'][0]['end'] = block['offset'] + len(n64_layout.encode(working[block['working_start']:block['working_start'] + block['size']], codec))
    with pytest.raises(ValueError, match='storage reserve'):
        n64_layout.repack(original, small, changed)


@pytest.mark.parametrize('large_clear', [False, True])
def test_startup_bss_relocations_and_interior_code_keep_original_bounds(tmp_path, large_clear):
    image = bytearray(0x200000)
    image[:16] = struct.pack('>4I', 0x80371240, 15, 0x80000400, 0)
    image[0x20:0x34] = b'ORIGINAL BOOT TEST'.ljust(20, b' ')
    # Original clear loop, with either a small immediate counter or a full
    # HI/LO counter. These require different handling by create_config.
    words = [0x3C0A8000, 0x254A4000]
    words += [0x3C0B0001, 0x256B0000] if large_clear else [0x240B0060]
    loop = len(words)
    words += [0x256BFFF8, 0xAD400000, 0xAD400004]
    branch = len(words)
    words += [0x15600000 | ((loop - branch - 1) & 0xFFFF), 0x254A0008,
              0x3C0C8000, 0x258C0460, 0x01800008, 0]
    image[0x1000:0x1000 + len(words) * 4] = struct.pack(f'>{len(words)}I', *words)
    image[0x1060:0x1060 + 1280] = _code(0x80000460, 40)
    image[0x2000:0x2500] = _code(0x80001400, 40)
    struct.pack_into('>2I', image, 0x10, *calculate(image, 6102))
    original = bytes(image)
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, toolchain='ido-5.3', confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'], result
    tree = Path(result['path'])
    assert (tree / 'build/game.z64').read_bytes() == original
    metadata = json.loads((tree / 'build.json').read_text())
    if not large_clear:
        assert metadata['symbols']['main_BSS_START'] == 0x80004000
    if large_clear:
        main_segment = next(s for s in metadata['segments'] if s['name'] == 'main')
        assert main_segment['bss_vram'] == 0x80004000
        assert main_segment['bss_size'] == 0x10000
        assert sum(f['seg'] == 'main' for f in metadata['functions']) >= 80


def test_external_automatic_jump_labels_keep_their_encoded_addresses(tmp_path):
    original, layout = resident_fixture()
    image = bytearray(original)
    struct.pack_into('>I', image, 0x1008, 0x0C000000 | ((0x84001064 >> 2) & 0x3FFFFFF))
    struct.pack_into('>2I', image, 0x10, *calculate(image, 6102))
    original = bytes(image)
    layout['sha256'] = hashlib.sha256(image).hexdigest()
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'], result
    assert (Path(result['path']) / 'build/game.z64').read_bytes() == original


def test_recorded_local_jump_table_labels_resolve_between_function_objects(tmp_path):
    original, layout = resident_fixture()
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    exported = net.export_rom(slug, log=lambda *_: None)
    assert exported['identical']
    tree = Path(exported['path'])
    metadata = json.loads((tree / 'build.json').read_text())
    second = sorted(metadata['functions'], key=lambda f: f['vram'])[1]
    name = 'jtbl_80000420'
    metadata['module_symbols']['main'][name] = second['vram']
    (tree / 'build.json').write_text(json.dumps(metadata))
    path = tree / second['asm']
    path.write_text(path.read_text().replace('glabel ' + second['name'], 'glabel ' + second['name'] + '\n' + name + ':'))
    for path in (tree / 'asm/data').glob('**/*.s'):
        path.write_text(path.read_text().replace(second['name'], name))
    process = run(tree)
    assert process.returncode == 0, process.stdout + process.stderr
    assert (tree / 'build/game.z64').read_bytes() == original
    with (tree / ('build/' + str(Path(second['asm']).with_suffix('.o')))).open('rb') as stream:
        elf = ELFFile(stream)
        symbol = next(s for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name == name)
        assert symbol['st_info']['bind'] == 'STB_GLOBAL'


def test_data_emitted_beside_nonmatching_code_is_placed_as_data(tmp_path, monkeypatch):
    from decompnet.rom import export
    original, layout = resident_fixture()
    net = RomNetwork(tmp_path / 'app.db', tmp_path / 'projects')
    slug = net.import_rom(original, reviewed_layout=layout, confirmed=True, log=lambda *_: None)
    original_run = subprocess.run

    def split_with_attached_data(argv, *args, **kwargs):
        result = original_run(argv, *args, **kwargs)
        if list(argv[1:4]) == ['-m', 'splat', 'split'] and result.returncode == 0:
            tree = Path(kwargs['cwd'])
            data = next((tree / 'asm/data').glob('**/*.data.s'))
            attached = tree / 'asm/nonmatchings/main/opaque.s'
            shutil.move(data, attached)
            text = attached.read_text()
            # Nonmatching fragments rely on their containing unit for Splat's
            # macros and assembler mode; ordinary data files supply their own.
            text = '\n'.join(line for line in text.splitlines()
                             if not line.lstrip().startswith(('.include', '.set')))
            attached.write_text(text + '\n')
        return result

    monkeypatch.setattr(export.subprocess, 'run', split_with_attached_data)
    result = net.export_rom(slug, log=lambda *_: None)
    assert result['identical'] and result['functions'] == 40, result
    tree = Path(result['path'])
    metadata = json.loads((tree / 'build.json').read_text())
    assert not any(f['name'] == 'opaque' for f in metadata['functions'])
    assert any(a['src'].endswith('opaque.s') for a in metadata['assembly'])
    assert (tree / 'build/game.z64').read_bytes() == original
