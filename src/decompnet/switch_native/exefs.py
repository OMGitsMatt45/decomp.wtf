"""Bounded ExeFS snapshot and ELF dynamic linking for source development.

The load order and MOD0/ELF layouts follow Kirikae's MIT loader at the revision
in sources.json (package.rs and dynamic.rs). This adapter resolves symbols and
RELA/RELR before translation, rather than running a guest dynamic linker.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from ..pc import PCError
from . import media

ORDER = ('rtld', 'main', *(f'subsdk{i}' for i in range(10)), 'sdk')
ALIGNMENT = 0x10000
PAGE_ALIGNMENT = 0x1000
LINK_PROFILE = 'switch-link.json'
MAX_LINK_PROFILE = 1 << 20
MAX_TOTAL = 512 * 1024 * 1024
MAX_RECORDS = 1 << 20
U64 = (1 << 64) - 1
RETURNS_TWICE = frozenset(('setjmp', '_setjmp', 'sigsetjmp', '__sigsetjmp'))


def module_alias(name):
    """Resolve NSS identity without interpreting embedded build paths as files."""
    value = name.replace('\\', '/').rsplit('/', 1)[-1]
    return value[:-4] if value.endswith('.nss') else value


def files(path):
    root = Path(path)
    if not root.is_dir():
        raise PCError('Switch runtime development requires an extracted ExeFS directory')
    nested = [p for p in root.iterdir() if p.name.lower() == 'exefs' and p.is_dir()]
    if len(nested) > 1:
        raise PCError('ambiguous Switch ExeFS directories')
    if nested:
        root = nested[0]
    names = {}
    for file in root.iterdir():
        key = file.name.lower()
        if key in names:
            raise PCError('ambiguous Switch file names: ' + key)
        names[key] = file
    selected = []
    for name in ORDER:
        candidates = [names[key] for key in (name, name + '.nso') if key in names]
        if len(candidates) > 1:
            raise PCError('duplicate Switch module: ' + name)
        if candidates:
            selected.append((name, candidates[0]))
    if not any(name == 'main' for name, _ in selected):
        raise PCError('Switch ExeFS requires a main NSO module')
    for name, file in selected + ([('main.npdm', names['main.npdm'])] if 'main.npdm' in names else []):
        if file.is_symlink() or not file.is_file():
            raise PCError('Switch source must be a regular file: ' + name)
    if any(key.endswith('.nso') and key[:-4] not in ORDER for key in names):
        raise PCError('unrecognized Switch NSO module name')
    return root, selected, names.get('main.npdm')


def read_link_profile(root):
    path = root / LINK_PROFILE
    if path.is_symlink():
        raise PCError('Switch link profile must be a regular file')
    if not path.exists():
        return None, None
    if not path.is_file():
        raise PCError('Switch link profile must be a regular file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_LINK_PROFILE + 1)
    if len(raw) > MAX_LINK_PROFILE:
        raise PCError('Switch link profile exceeds 1 MiB')

    def unique_fields(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError('duplicate profile field')
        return value

    try:
        profile = json.loads(raw, object_pairs_hook=unique_fields)
    except (ValueError, RecursionError) as error:
        raise PCError('Invalid Switch link profile JSON') from error
    if (not isinstance(profile, dict)
            or set(profile) - {'schema', 'alignment', 'inputs', 'imports', 'entries'}
            or profile.get('schema') != 'decomp.wtf.switch-link/v1'
            or type(profile.get('alignment')) is not int or profile['alignment'] != PAGE_ALIGNMENT
            or any(not isinstance(profile.get(key, {}), dict) for key in ('inputs', 'imports', 'entries'))):
        raise PCError('Invalid Switch link profile schema or alignment')
    return profile, dict(name=LINK_PROFILE, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def bind_link_profile(inputs, profile, identity):
    if profile is None:
        return
    if profile.get('inputs') != {item['name']: item['sha256'] for item in inputs}:
        raise PCError('Switch link profile does not match the exact ExeFS inputs')
    inputs.append(identity)


def identify_inputs(path):
    root, selected, npdm = files(path)
    profile, identity = read_link_profile(root)
    paths = [file for _, file in selected] + ([npdm] if npdm else [])
    result = []
    for file in paths:
        with file.open('rb') as stream:
            result.append(dict(name=file.name, size=file.stat().st_size,
                               sha256=hashlib.file_digest(stream, 'sha256').hexdigest()))
    bind_link_profile(result, profile, identity)
    return result


def valid_link_profile_offset(owner, offset):
    text, rodata, data = owner['segments']
    return (0 <= offset < text['size'] and offset % 4 == 0
            or rodata['offset'] <= offset < rodata['offset'] + rodata['size']
            or data['offset'] <= offset < data['offset'] + data['size'] + owner['bss_size'])


def link_profile_targets(profile, modules):
    if profile is None:
        return {}
    by_name = {module['name']: module for module in modules}
    imports = {}
    for name, target in profile.get('imports', {}).items():
        if (not name or '\0' in name or not isinstance(target, dict) or set(target) != {'module', 'offset'}
                or not isinstance(target['module'], str) or target['module'] not in by_name
                or type(target['offset']) is not int):
            raise PCError('Invalid Switch link profile import: ' + name)
        owner, offset = by_name[target['module']], target['offset']
        if not valid_link_profile_offset(owner, offset):
            raise PCError('Switch link profile import offset is outside a segment or unaligned: ' + name)
        imports[name] = owner, offset
    for name, offsets in profile.get('entries', {}).items():
        if name not in by_name or not isinstance(offsets, list):
            raise PCError('Invalid Switch link profile entries for ' + name)
        owner = by_name[name]
        text_size = owner['segments'][0]['size']
        if any(type(offset) is not int or not 0 <= offset < text_size or offset % 4 for offset in offsets):
            raise PCError('Switch link profile entry is outside executable text or unaligned: ' + name)
        owner.setdefault('_extra_roots', set()).update(owner['base'] + offset for offset in offsets)
    return imports


class View:
    def __init__(self, module):
        self.module = module
        self.image = module['image']
        self.regions = [(s['offset'], s['offset'] + s['size']) for s in module['segments'] if s['size']]
        data = module['segments'][2]
        self.writable_end = data['offset'] + data['size'] + module['bss_size']

    def read(self, offset, count):
        if offset < 0 or count < 0 or not any(start <= offset and offset + count <= end for start, end in self.regions):
            raise PCError(f"{self.module['name']}: dynamic metadata outside initialized segments")
        return self.image[offset:offset + count]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.read(offset, struct.calcsize(fmt)))

    def target(self, offset):
        regions = self.regions + [(self.module['segments'][2]['offset'], self.writable_end)]
        if offset % 8 or not any(start <= offset and offset + 8 <= end for start, end in regions):
            raise PCError(f"{self.module['name']}: relocation target outside a segment or unaligned")


def dynamic(module):
    view = View(module)
    image = module['image']
    mod0 = struct.unpack_from('<I', image, 4)[0] if len(image) >= 8 else 0
    empty = dict(tags={}, symbols=[], relocs=[], needed=[], soname=None)
    if not mod0:
        return empty
    record = view.read(mod0, 28)
    if record[:4] != b'MOD0':
        raise PCError(module['name'] + ': invalid MOD0 header')
    start = mod0 + struct.unpack_from('<i', record, 4)[0]
    tags = {}
    needed_offsets = []
    for i in range(4096):
        tag, value = view.unpack('<QQ', start + i * 16)
        if tag == 0:
            break
        if tag == 1:
            needed_offsets.append(value)
        elif tag in tags:
            raise PCError(module['name'] + ': duplicate dynamic tag')
        else:
            tags[tag] = value
    else:
        raise PCError(module['name'] + ': unterminated dynamic table')
    if any(tag in tags for tag in (0x6ffffff0, 0x6ffffffe, 0x6ffffffc)):
        raise PCError(module['name'] + ': versioned dynamic symbols are not supported')
    string_table = view.read(tags.get(5, 0), tags.get(10, 0)) if 5 in tags else b''

    def string(offset):
        if not 0 <= offset < len(string_table):
            raise PCError(module['name'] + ': invalid dynamic string offset')
        end = string_table.find(b'\0', offset, min(len(string_table), offset + 4097))
        if end < 0:
            raise PCError(module['name'] + ': unterminated dynamic string')
        try:
            return string_table[offset:end].decode('utf-8')
        except UnicodeDecodeError as error:
            raise PCError(module['name'] + ': invalid dynamic string encoding') from error

    symbols = []
    if 6 in tags:
        if tags.get(11, 24) != 24 or 5 not in tags or 10 not in tags:
            raise PCError(module['name'] + ': invalid symbol/string table layout')
        if 4 in tags:
            buckets, count = view.unpack('<II', tags[4])
            if not 0 < buckets <= MAX_RECORDS or not 0 < count <= MAX_RECORDS:
                raise PCError(module['name'] + ': invalid ELF hash table bounds')
            view.read(tags[4], 8 + 4 * (buckets + count))
        elif 0x6ffffef5 in tags:
            gnu = tags[0x6ffffef5]
            buckets, first, bloom, _ = view.unpack('<IIII', gnu)
            if not 0 < buckets <= MAX_RECORDS or not 0 < bloom <= MAX_RECORDS or first > MAX_RECORDS:
                raise PCError(module['name'] + ': invalid GNU hash bounds')
            at = gnu + 16 + bloom * 8
            view.read(gnu, 16 + bloom * 8 + buckets * 4)
            bucket_values = view.unpack('<' + str(buckets) + 'I', at)
            count = first
            steps = 0
            for bucket in bucket_values:
                if not bucket:
                    continue
                if not first <= bucket < MAX_RECORDS:
                    raise PCError(module['name'] + ': invalid GNU hash bucket')
                index = bucket
                while index < MAX_RECORDS:
                    steps += 1
                    if steps > MAX_RECORDS:
                        raise PCError(module['name'] + ': GNU hash traversal exceeds its bound')
                    (chain,) = view.unpack('<I', at + buckets * 4 + (index - first) * 4)
                    index += 1
                    if chain & 1:
                        break
                else:
                    raise PCError(module['name'] + ': unterminated GNU hash chain')
                count = max(count, index)
        else:
            difference = tags[5] - tags[6]
            if difference <= 0 or difference % 24:
                raise PCError(module['name'] + ': no bounded dynamic symbol count')
            count = difference // 24
        if count > MAX_RECORDS:
            raise PCError(module['name'] + ': too many dynamic symbols')
        view.read(tags[6], count * 24)
        for i in range(count):
            name, info, visibility, section, value, size = view.unpack('<IBBHQQ', tags[6] + i * 24)
            symbol = dict(name=string(name), binding=info >> 4, kind=info & 15,
                          visibility=visibility & 3, section=section, value=value, size=size)
            if section not in (0, 0xfff1, 0xfff2) and (value > len(image) or size > len(image) - value):
                raise PCError(module['name'] + ': symbol exceeds its module')
            symbols.append(symbol)
        if symbols and any(symbols[0][key] for key in ('name', 'binding', 'kind', 'section', 'value', 'size')):
            raise PCError(module['name'] + ': invalid ELF null symbol')
    relocs = []
    if 17 in tags or 18 in tags:
        raise PCError(module['name'] + ': ELF REL relocations are not supported')
    for table, size_tag in ((7, 8), (23, 2)):
        if table not in tags and size_tag not in tags:
            continue
        if table not in tags or size_tag not in tags or tags[size_tag] % 24 or tags[size_tag] // 24 > MAX_RECORDS:
            raise PCError(module['name'] + ': invalid RELA table size')
        if table == 7 and tags.get(9, 24) != 24 or table == 23 and tags.get(20, 7) != 7:
            raise PCError(module['name'] + ': unsupported relocation entry format')
        view.read(tags[table], tags[size_tag])
        for i in range(tags[size_tag] // 24):
            off, info, addend = view.unpack('<QQq', tags[table] + i * 24)
            kind, symbol = info & 0xffffffff, info >> 32
            if kind == 0:
                continue
            if kind not in (257, 1025, 1026, 1027) or kind == 1027 and symbol:
                raise PCError(f"{module['name']}: unsupported AArch64 relocation {kind}")
            view.target(off)
            if kind != 1027 and not 0 < symbol < len(symbols):
                raise PCError(module['name'] + ': invalid relocation symbol index')
            relocs.append(dict(offset=off, kind=kind, symbol=symbol, addend=addend))
    if 36 in tags or 35 in tags:
        if 36 not in tags or 35 not in tags or tags[35] % 8 or tags[35] // 8 > MAX_RECORDS or tags.get(37, 8) != 8:
            raise PCError(module['name'] + ': invalid RELR table size')
        cursor = None
        for at in range(tags[36], tags[36] + tags[35], 8):
            (word,) = view.unpack('<Q', at)
            if not word & 1:
                offsets = [word]
                cursor = word + 8
            else:
                if cursor is None:
                    raise PCError(module['name'] + ': RELR bitmap has no base')
                offsets = [cursor + (bit - 1) * 8 for bit in range(1, 64) if word & (1 << bit)]
                cursor += 63 * 8
            for offset in offsets:
                view.target(offset)
                (addend,) = struct.unpack_from('<Q', image, offset)
                relocs.append(dict(offset=offset, kind=1027, symbol=0, addend=addend))
                if len(relocs) > MAX_RECORDS:
                    raise PCError(module['name'] + ': too many relocations')
    ordered = sorted(r['offset'] for r in relocs)
    if len(ordered) > MAX_RECORDS:
        raise PCError(module['name'] + ': too many relocations')
    if any(b < a + 8 for a, b in zip(ordered, ordered[1:])):
        raise PCError(module['name'] + ': overlapping relocation targets')
    for address, size_tag in ((25, 27), (32, 33)):
        size = tags.get(size_tag, 0)
        if size % 8 or size > 4096 * 8 or size and address not in tags:
            raise PCError(module['name'] + ': invalid initializer array')
        if size:
            view.read(tags[address], size)
    return dict(tags=tags, symbols=symbols, relocs=relocs,
                needed=[string(n) for n in needed_offsets], soname=string(tags[14]) if 14 in tags else None)


def load(path, *, include_images=False, single=False):
    if single and Path(path).is_file():
        root, paths, npdm = Path(path).parent, [('main', Path(path))], None
        profile, identity = None, None
    else:
        root, paths, npdm = files(path)
        profile, identity = read_link_profile(root)
    if sum(file.stat().st_size for _, file in paths) > 1024 * 1024 * 1024:
        raise PCError('Switch ExeFS inputs exceed 1 GiB')
    modules, inputs = [], []
    base = media.BASE
    alignment = profile['alignment'] if profile else ALIGNMENT
    stack_size = 0x10000
    system_resource_size = 0
    for name, file in paths:
        module = media.load(file, include_image=True)
        if module['format'] != 'nso':
            raise PCError('Switch ExeFS modules must be NSO files')
        module.update(name=name, base=base, entry=base, image=bytearray(module['image']))
        module['_dynamic'] = dynamic(module)
        modules.append(module)
        inputs.append(module['input'])
        base = (base + module['image_size'] + alignment - 1) & ~(alignment - 1)
        if sum(m['image_size'] for m in modules) > MAX_TOTAL:
            raise PCError('Switch linked images exceed 512 MiB')
    if npdm:
        if not 0x80 <= npdm.stat().st_size <= 1 << 20:
            raise PCError('invalid Switch NPDM size')
        raw = npdm.read_bytes()
        if raw[:4] != b'META':
            raise PCError('invalid Switch NPDM header')
        declared = struct.unpack_from('<I', raw, 0x1c)[0]
        if declared and (not 0x4000 <= declared <= 16 * 1024 * 1024 or declared % 0x1000):
            raise PCError('Switch NPDM stack exceeds development bounds or is unaligned')
        stack_size = declared or stack_size
        system_resource_size = struct.unpack_from('<I', raw, 0x14)[0]
        if system_resource_size > 0x1fe00000 or system_resource_size % 0x1000:
            raise PCError('Switch NPDM system resource size is out of bounds or is unaligned')
        inputs.append(dict(name=npdm.name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    bind_link_profile(inputs, profile, identity)
    fallback_imports = link_profile_targets(profile, modules)
    aliases = {}
    definitions = {}

    def address(module, symbol):
        if symbol['section'] == 0xfff2 or symbol['kind'] in (6, 10):
            raise PCError(module['name'] + ': common, TLS and indirect-function symbols are unsupported')
        return symbol['value'] if symbol['section'] == 0xfff1 else module['base'] + symbol['value']

    for module in modules:
        meta = module['_dynamic']
        for alias in (module['name'], meta['soname'], module.get('module_name')):
            if alias:
                alias = module_alias(alias)
                if not alias:
                    continue
                if alias in aliases and aliases[alias] is not module:
                    raise PCError('ambiguous Switch module SONAME: ' + alias)
                aliases[alias] = module
        for symbol in meta['symbols']:
            if symbol['name'] and symbol['section'] and symbol['binding'] in (1, 2) and symbol['visibility'] in (0, 3):
                definitions.setdefault(symbol['name'], []).append((module, symbol))

    def code_module(pointer):
        return next((m for m in modules if m['base'] <= pointer < m['base'] + m['segments'][0]['size'] and pointer % 4 == 0), None)

    for module in modules:
        meta = module['_dynamic']
        roots = {module['base']}
        imports = []
        returns_twice = []
        return_slots = []
        for symbol in meta['symbols']:
            if symbol['section'] and symbol['kind'] == 2:
                value = address(module, symbol)
                if code_module(value) is not module:
                    raise PCError(module['name'] + ': function symbol outside executable text')
                roots.add(value)
                if symbol['name'] in RETURNS_TWICE:
                    returns_twice.append(value)
        module['_roots'] = roots
        module['dynamic'] = dict(symbols=len(meta['symbols']), relocations=len(meta['relocs']),
                                 needed=meta['needed'], soname=meta['soname'], imports=imports)
        for needed in meta['needed']:
            if module_alias(needed) not in aliases:
                raise PCError(f"{module['name']}: missing DT_NEEDED module {needed}")
        for reloc in meta['relocs']:
            if reloc['kind'] == 1027:
                value = module['base'] + reloc['addend']
            else:
                symbol = meta['symbols'][reloc['symbol']]
                candidates = definitions.get(symbol['name'], [])
                if symbol['section'] and (symbol['binding'] == 0 or symbol['visibility'] in (1, 2, 3)
                        or 16 in meta['tags'] or meta['tags'].get(30, 0) & 2):
                    owner, found = module, symbol
                elif candidates and symbol['visibility'] in (0, 3):
                    owner, found = next(((m, s) for m, s in candidates if s['binding'] == 1), candidates[0])
                elif symbol['binding'] == 2 and not symbol['section']:
                    owner, found = None, None
                elif (not symbol['section'] and symbol['binding'] == 1 and symbol['visibility'] in (0, 3)
                        and (fallback := fallback_imports.get(symbol['name'])) is not None):
                    owner, offset = fallback
                    target_offset = offset + reloc['addend']
                    if reloc['kind'] == 1026 or symbol['kind'] == 2:
                        if (code_module(owner['base'] + offset) is not owner
                                or code_module(owner['base'] + target_offset) is not owner):
                            raise PCError('Switch link profile function import requires aligned executable text: '
                                          + symbol['name'])
                    elif not valid_link_profile_offset(owner, target_offset):
                        raise PCError('Switch link profile relocated import is outside an owning segment or unaligned: '
                                      + symbol['name'])
                    found = dict(symbol, section=1, value=offset)
                else:
                    raise PCError(f"{module['name']}: unresolved Switch import {symbol['name']}")
                value = (address(owner, found) if found else 0) + reloc['addend']
                if reloc['kind'] == 1026 and symbol['name'] in RETURNS_TWICE and code_module(value):
                    return_slots.append(module['base'] + reloc['offset'])
                if not symbol['section']:
                    binding = dict(name=symbol['name'], address=value & U64, module=owner['name'] if owner else None)
                    if binding not in imports:
                        imports.append(binding)
            struct.pack_into('<Q', module['image'], reloc['offset'], value & U64)
            target = code_module(value & U64)
            if target:
                target.setdefault('_extra_roots', set()).add(value & U64)
        if returns_twice or return_slots:
            module['returns_twice'] = dict(functions=sorted(set(returns_twice)), slots=sorted(return_slots))
    initializers, visiting, initialized = [], set(), set()

    def array(module, tag, size_tag):
        tags = module['_dynamic']['tags']
        out = []
        for offset in range(tags.get(tag, 0), tags.get(tag, 0) + tags.get(size_tag, 0), 8):
            (value,) = struct.unpack_from('<Q', module['image'], offset)
            if value not in (0, U64):
                if not code_module(value):
                    raise PCError(module['name'] + ': initializer is not a linked code address')
                code_module(value).setdefault('_extra_roots', set()).add(value)
                out.append(value)
        return out

    main = aliases['main']
    initializers.extend(array(main, 32, 33))

    def initialize(module):
        name = module['name']
        if name in initialized or name in visiting:
            return
        visiting.add(name)
        for needed in module['_dynamic']['needed']:
            initialize(aliases[module_alias(needed)])
        tags = module['_dynamic']['tags']
        if tags.get(12):
            pointer = module['base'] + tags[12]
            target = code_module(pointer)
            if not target:
                raise PCError(name + ': DT_INIT is outside executable code')
            target.setdefault('_extra_roots', set()).add(pointer)
            initializers.append(pointer)
        initializers.extend(array(module, 25, 27))
        visiting.remove(name)
        initialized.add(name)

    for module in modules:
        initialize(module)
    sdk_start_name = '_ZN2nn4init5StartEmmPFvvES2_'
    sdk_start_with_fini = sdk_start_name + 'S2_'
    sdk_starts = [(m, s) for name in (sdk_start_name, sdk_start_with_fini)
                  for m, s in definitions.get(name, []) if s['kind'] == 2]
    startup = None
    if sdk_starts:
        if len(sdk_starts) != 1:
            raise PCError('ambiguous Nintendo SDK startup symbol')
        owner, symbol = sdk_starts[0]
        pointer = address(owner, symbol)
        if code_module(pointer) is not owner:
            raise PCError('Nintendo SDK startup is outside executable text')

        def constructors(module):
            tags = module['_dynamic']['tags']
            # Nintendo's DT_INIT registers the DSO/TLS template and invokes
            # its own init_array. Calling the array again initializes twice.
            return [module['base'] + tags[12]] if tags.get(12) else array(module, 25, 27)

        order, seen = [], set()

        def sdk_order(module):
            if module['name'] in seen or module['name'] in ('rtld', 'main'):
                return
            seen.add(module['name'])
            for needed in module['_dynamic']['needed']:
                sdk_order(aliases[module_alias(needed)])
            order.append(module)

        sdk_order(owner)
        for module in modules:
            sdk_order(module)
        sdk_initializers = [pointer for module in order for pointer in constructors(module)]
        main_initializers = constructors(main)
        startup = dict(model='nn-sdk-start', entry=pointer,
                       sdk_initializers=sdk_initializers, main_initializers=main_initializers)
        if symbol['name'] == sdk_start_with_fini:
            # With three callbacks, RTLD's first callback only marks itself ready.
            # The second initializes all DSOs after nninitStartup and the third
            # calls DT_FINI in reverse order after nnMain returns.
            finalizers = []
            for module in reversed(order + [main]):
                offset = module['_dynamic']['tags'].get(13)
                if offset:
                    finalizer = module['base'] + offset
                    if code_module(finalizer) is not module:
                        raise PCError(module['name'] + ': DT_FINI is outside executable code')
                    module.setdefault('_extra_roots', set()).add(finalizer)
                    finalizers.append(finalizer)
            startup.update(sdk_initializers=[], main_initializers=sdk_initializers + main_initializers,
                           finalizers=finalizers)
    for module in modules:
        module['roots'] = sorted(module.pop('_roots') | module.pop('_extra_roots', set()))
        module.pop('_dynamic')
        if include_images:
            module['image'] = bytes(module['image'])
        else:
            module.pop('image')
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(platform='switch', format='exefs', input=dict(name=root.name, sha256=digest), inputs=inputs,
                entry=main['base'], stack_size=stack_size, system_resource_size=system_resource_size,
                modules=modules, initializers=initializers,
                native_game_backend_available=False, scope='host-linked-module-runtime-development', startup=startup)
