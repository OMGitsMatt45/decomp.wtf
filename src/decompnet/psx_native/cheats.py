"""Bounded owner GameShark data and guarded native instruction choices."""
import itertools
import json
from pathlib import Path
import re
import struct

from .. import pc

MAX_WRITES = 16384


def load(path):
    path = Path(path)
    if path.stat().st_size > 1 << 20:
        raise pc.PCError('PS1 cheat file exceeds 1 MiB')
    entries = []
    raw = []
    current = None

    def finish():
        if current is None:
            return
        current['operations'] = decode(raw)
        if not current['operations']:
            raise pc.PCError('empty PS1 cheat: ' + current['name'])
        entries.append(current.copy())

    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith((';', '#')):
            continue
        if line.startswith('[') and line.endswith(']'):
            finish()
            name = line[1:-1]
            if not name or len(name) > 256 or any(row['name'] == name for row in entries):
                raise pc.PCError('invalid or repeated PS1 cheat name')
            current = dict(name=name, description='', group=name.rsplit('\\', 1)[0] if '\\' in name else '')
            raw = []
        elif current is None:
            raise pc.PCError(f'PS1 cheat data before section at line {number}')
        elif '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            if key == 'Description':
                current['description'] = value
            elif key == 'Type' and value.lower() != 'gameshark':
                raise pc.PCError('PS1 cheats require Type = Gameshark')
            elif key == 'Activation' and value != 'EndFrame':
                raise pc.PCError('PS1 cheats require Activation = EndFrame')
            elif key not in ('Type', 'Activation', 'Description'):
                raise pc.PCError('unsupported PS1 cheat property: ' + key)
        elif re.fullmatch(r'[0-9A-Fa-f]{8}\s+[0-9A-Fa-f]{4}(?:[0-9A-Fa-f]{4})?', line):
            raw.append(tuple(int(word, 16) for word in line.split()))
        else:
            raise pc.PCError(f'invalid PS1 cheat line {number}')
    finish()
    if not 1 <= len(entries) <= 256 or sum(len(row['operations']) for row in entries) > MAX_WRITES:
        raise pc.PCError('PS1 cheat catalog exceeds its bound')
    return entries


def decode(lines):
    result = []
    condition = None
    at = 0
    while at < len(lines):
        command, value = lines[at]
        kind = command >> 24
        address = command & 0xffffff
        count, stride, increment = 1, 0, 0
        if kind == 0xd0:
            if condition is not None or value > 0xffff:
                raise pc.PCError('unsupported chained PS1 condition')
            condition = dict(address=address, value=value)
            if address & 1 or address > 0x1ffffe:
                raise pc.PCError('PS1 condition is outside aligned RAM')
            at += 1
            continue
        if kind == 0x50:
            count, stride, increment = command >> 8 & 0xff, command & 0xff, value
            at += 1
            if not count or at >= len(lines) or value > 0xffff:
                raise pc.PCError('invalid PS1 slide')
            command, value = lines[at]
            kind, address = command >> 24, command & 0xffffff
            if kind not in (0x30, 0x80, 0x90):
                raise pc.PCError('unsupported PS1 slide write')
        if kind not in (0x30, 0x80, 0x90, 0xa7):
            raise pc.PCError(f'unsupported PS1 GameShark opcode {kind:02x}')
        width = 1 if kind == 0x30 else 4 if kind == 0x90 else 2
        if kind != 0xa7 and value >= 1 << (width * 8):
            raise pc.PCError('PS1 cheat value exceeds write width')
        for index in range(count):
            target = address + stride * index
            if target < 0 or target + width > 0x200000 or target % width:
                # Original GameShark halfword codes in packed structures may
                # be unaligned. Byte-wise RAM accesses retain their meaning.
                if target < 0 or target + width > 0x200000 or width != 2:
                    raise pc.PCError('PS1 cheat write is outside RAM')
            op = dict(address=target, width=width, value=(value + increment * index) & ((1 << (width * 8)) - 1))
            if kind == 0xa7:
                op.update(match=value >> 16, restore=True)
            if condition is not None:
                op['condition'] = condition.copy()
            result.append(op)
            if len(result) > MAX_WRITES:
                raise pc.PCError('PS1 cheat program exceeds its write bound')
        condition = None
        at += 1
    if condition is not None:
        raise pc.PCError('PS1 condition has no following write')
    return result


def code_ranges(dispatch):
    text = dispatch.read_text(encoding='utf-8')
    marker = 'static const PsxGameCodeRange k_psx_game_code_ranges[] = {'
    if text.count(marker) != 1:
        raise pc.PCError('pinned PS1 code footprint table differs')
    table = text.split(marker, 1)[1].split('};', 1)[0]
    return sorted(set((int(lo, 16) & 0x1fffffff, int(length, 16))
        for lo, length in re.findall(r'\{0x([0-9A-Fa-f]+)u, 0x([0-9A-Fa-f]+)u\}', table)))


def variant_images(item, entries, ranges):
    """Finite source-derived choices; each emitted view keeps full byte guards."""
    low = item['info']['load'] & 0x1fffffff
    original = item['image'][2048:]

    def read(data, address, width):
        offset = address - low
        return int.from_bytes(data[offset:offset+width], 'little') if 0 <= offset <= len(data)-width else None

    def apply(data, entry):
        changed = False
        for op in entry['operations']:
            address, width = op['address'], op['width']
            if not any(address < start+length and address+width > start for start, length in ranges):
                continue
            if not low <= address <= low+len(data)-width:
                raise pc.PCError('PS1 native cheat footprint exceeds its image')
            cond = op.get('condition')
            if cond and read(data, cond['address'], 2) not in (None,cond['value']):
                continue
            before = read(data, address, width)
            if 'match' in op and before != op['match']:
                continue
            after = op['value']
            if before != after:
                op['code'] = True
                offset = address-low
                data[offset:offset+width] = after.to_bytes(width, 'little')
                changed = True
        return changed

    groups = {}
    for index, entry in enumerate(entries):
        if apply(bytearray(original), entry):
            groups.setdefault(entry['group'] or f'entry:{index}', []).append(index)
    count = 1
    for values in groups.values():
        count *= len(values)+1
    if count > 32:
        raise pc.PCError('PS1 native cheat combinations exceed 32 per code image')
    seen = {original}
    for choice in itertools.product(*[[-1, *values] for values in groups.values()]):
        selected = [index for index in choice if index >= 0]
        if not selected:
            continue
        data = bytearray(original)
        for index in selected:
            apply(data, entries[index])
        raw = bytes(data)
        if raw not in seen:
            seen.add(raw)
            yield dict(item, image=item['image'][:2048]+raw,
                boot='CHEAT_VARIANT.EXE',
                source=dict(format='cheat-native-variant', program=item['boot'],
                    enabled=[entries[index]['name'] for index in selected]))


def emit(entries, root):
    (root/'game/cheats.json').write_text(json.dumps(dict(schema='decomp.wtf.ps1-cheats/v1', entries=entries), indent=2)+'\n', encoding='utf-8')
    lines = ['inline std::vector<Cheat> cheats={']
    for entry in entries:
        lines.append('{'+','.join(json.dumps(entry[key], ensure_ascii=True) for key in ('name','description','group'))+',{')
        for op in entry['operations']:
            condition = op.get('condition', {})
            values = [op['address'],op['value'],condition.get('address',0),condition.get('value',0),op.get('match',0),op['width']]
            flags = ['condition' in op,'match' in op,op.get('restore',False),op.get('code',False)]
            lines.append('{'+','.join([*(str(value)+'u' for value in values),*('true' if flag else 'false' for flag in flags)])+'},')
        lines.append('}},')
    lines.append('};')
    (root/'native/cheat_catalog.inc').write_text('\n'.join(lines)+'\n', encoding='utf-8')
