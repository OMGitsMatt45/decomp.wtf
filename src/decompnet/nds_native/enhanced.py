"""Private NTR analysis views of enhanced cartridges; runtime assets stay intact.

The pinned decoder expects three-word autoload descriptors and NTR startup
heuristics. A temporary analysis entry supplies that shape, tail-calling the
real entry. Its bytes and changed parameter words never enter emitted images.
No DSi-exclusive program, key, network service or enhanced hardware is enabled.
"""
from dataclasses import dataclass
from pathlib import Path
import struct
import shutil

import yaml

from ..forks.scratch_dsd import crc16
from ..rom.nds_modules import MAX_MODULE_SIZE, NdsImage, decompress_blz


@dataclass(frozen=True)
class Layout:
    params: int
    source: int
    list_start: int
    list_end: int
    bss_start: int
    bss_end: int
    blocks: tuple


def layout(image, base):
    """Validate referenced SDK-5 four-word autoload metadata and exact payloads."""
    candidates = []
    for at in range(28, min(len(image) - 7, 0x4000), 4):
        if struct.unpack_from('<2I', image, at) != (0xDEC00621, 0x2106C0DE):
            continue
        params = at - 28
        start, end, source, bss_start, bss_end, compressed, version = struct.unpack_from('<7I', image, params)
        if version >> 24 != 5 or not base <= source <= start < end <= base + len(image):
            continue
        if (end - start) % 16 or not 0 < (end - start) // 16 <= 64 or not 0 <= bss_start <= bss_end <= 0x100000000:
            continue
        if struct.pack('<I', base + params) not in image[:params] + image[at + 8:min(len(image), 0x4000)]:
            continue
        cursor = source - base
        blocks = []
        for position in range(start - base, end - base, 16):
            address, size, init, bss = struct.unpack_from('<4I', image, position)
            if (address % 4 or size % 4 or size > MAX_MODULE_SIZE or bss > MAX_MODULE_SIZE
                    or not size + bss or address + size + bss > 0x100000000
                    or not address <= init <= address + size or cursor + size > start - base
                    or any(address < a + n + z and a < address + size + bss for a, n, _, z, _ in blocks)):
                break
            blocks.append((address, size, init, bss, cursor))
            cursor += size
        else:
            if cursor == start - base:
                candidates.append(Layout(params, source, start, end, bss_start, bss_end, tuple(blocks)))
    if len(candidates) != 1:
        raise ValueError('enhanced NTR input needs one validated referenced four-word autoload layout')
    return candidates[0]


def _arm9_image(raw, module):
    image = raw[module.offset:module.offset + module.stored_size]
    # The parameter prefix remains uncompressed. Its compression end must
    # describe exactly this header extent, never an arbitrary scanning hint.
    markers = [at - 28 for at in range(28, min(len(image) - 7, 0x4000), 4)
               if struct.unpack_from('<2I', image, at) == (0xDEC00621, 0x2106C0DE)
               and struct.unpack_from('<I', image, at - 4)[0] >> 24 == 5]
    if len(markers) != 1:
        raise ValueError('enhanced ARM9 compression metadata is absent or ambiguous')
    compressed = struct.unpack_from('<I', image, markers[0] + 20)[0]
    if compressed:
        if compressed != module.address + len(image):
            raise ValueError('enhanced ARM9 compression end differs from the header extent')
        image = decompress_blz(image, len(image) + int.from_bytes(image[-4:], 'little'))
    return image


def stage(source, target, *, input_format):
    """Build an analysis-only decoder container; return exact restoration facts."""
    raw = Path(source).read_bytes()
    parsed = NdsImage(raw, allow_dsi_enhanced=True)
    if not parsed.dsi_enhanced:
        raise ValueError('enhanced staging requires a DS-compatible enhanced cartridge')
    main = parsed.modules['arm9']
    if input_format != 'decrypted' and raw[main.offset:main.offset + 8] != bytes.fromhex('ffdeffe7ffdeffe7'):
        raise ValueError('enhanced NTR analysis currently requires an explicitly decrypted secure area')
    original = _arm9_image(raw, main)
    info = layout(original, main.address)
    entry = struct.unpack_from('<I', raw, 0x24)[0]
    split = info.source - main.address
    if split % 32 or entry % 4 or not main.address <= entry < info.source:
        raise ValueError('enhanced NTR analysis needs an aligned ARM startup and static/autoload split')
    canonical = bytearray(original[:split] + bytes(32) + original[split:])
    for index, (address, size, init, bss, position) in enumerate(info.blocks):
        struct.pack_into('<3I', canonical, info.list_start - main.address + 32 + 12 * index, address, size, bss)
    struct.pack_into('<4I', canonical, info.params, info.list_start + 32,
                     info.list_start + 32 + 12 * len(info.blocks), info.source + 32, info.source + 32)
    struct.pack_into('<I', canonical, info.params + 20, 0)
    # A decoder-only NTR entry has a conventional empty ctor runner and a
    # literal tail target naming the original startup. No game code is patched.
    wrapper = info.source
    struct.pack_into('<8I', canonical, split, 0xEB000002, 0xE59F3000, 0xE12FFF13, entry,
                     0xE59F0000, 0xE12FFF1E, wrapper + 28, 0)
    staged = bytearray(raw)
    offset = len(staged) + (-len(staged) % 512)
    staged.extend(bytes(offset - len(staged)))
    staged.extend(canonical)
    staged.extend(struct.pack('<3I', 0xDEC00621, info.params, 0))
    staged[0x12] = 0
    staged[0x1C] &= ~3
    struct.pack_into('<4I', staged, 0x20, offset, wrapper, main.address, len(canonical))
    struct.pack_into('<I', staged, 0x80, len(staged))
    struct.pack_into('<H', staged, 0x15E, crc16(staged[:0x15E]))
    Path(target).write_bytes(staged)
    return dict(main_size=split, base=main.address, entry=entry, params=info.params,
                parameter_hex=original[info.params:info.params + 24].hex(),
                original_prefix_hex=original[:0x800].hex(),
                autoloads=[dict(index=i, address=a, size=s, init=n, bss=b)
                           for i, (a, s, n, b, _) in enumerate(info.blocks)])


def dtcm_base(image, base):
    """Read a declared DTCM base from an adjacent literal/ORR/CP15 sequence."""
    found = set()
    for at in range(8, min(len(image) - 3, 0x4000), 4):
        load, size, control = struct.unpack_from('<3I', image, at - 8)
        if control & 0xFFFF0FFF != 0xEE090F11:
            continue
        register = (control >> 12) & 15
        if (size & 0xFFFFF000 != 0xE3800000 | register << 16 | register << 12
                or size & 0xFFF != 0xA or load & 0xFF7FF000 != 0xE51F0000 | register << 12):
            continue
        literal = at - 8 + 8 + ((load & 0xFFF) if load & 0x800000 else -(load & 0xFFF))
        if 0 <= literal <= len(image) - 4:
            found.add(struct.unpack_from('<I', image, literal)[0] & 0xFFFFF000)
    if len(found) != 1:
        raise ValueError('enhanced DTCM base is not uniquely declared by startup CP15 code')
    return found.pop()


def prepare_extracted(extracted):
    """Identify relocated DTCM by its declared CP15 base, preserving all blocks."""
    arm9 = extracted / 'arm9'
    if not (arm9 / 'itcm.bin').exists():
        raise ValueError('enhanced NTR analysis needs a recognized ITCM block')
    if (arm9 / 'dtcm.bin').exists():
        return
    config_path = extracted / 'config.yaml'
    config = yaml.safe_load(config_path.read_text())
    main = yaml.safe_load((arm9 / 'arm9.yaml').read_text())
    base = dtcm_base((arm9 / 'arm9.bin').read_bytes(), int(main['base_address']))
    matches = []
    for item in config.get('unknown_autoloads', []):
        metadata = yaml.safe_load((extracted / item['config']).read_text())
        if int(metadata['base_address']) == base:
            matches.append((item, metadata))
    if len(matches) != 1:
        raise ValueError('declared enhanced DTCM does not match one extracted autoload')
    item, metadata = matches[0]
    shutil.copyfile(extracted / item['bin'], arm9 / 'dtcm.bin')
    metadata['kind'] = 'Dtcm'
    (arm9 / 'dtcm.yaml').write_text(yaml.safe_dump(metadata), encoding='utf-8')
    config['unknown_autoloads'].remove(item)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')


def restore_images(extracted, images, facts):
    """Remove the synthetic entry and restore original mutable parameter words."""
    for path in {extracted / 'arm9/arm9.bin', images / 'arm9.bin'}:
        data = bytearray(path.read_bytes())
        if len(data) != facts['main_size'] + 32:
            raise ValueError('enhanced decoder changed the expected static analysis extent')
        data = data[:facts['main_size']]
        at = facts['params']
        data[at:at + 24] = bytes.fromhex(facts['parameter_hex'])
        path.write_bytes(data)


def restore_manifest(manifest, config, images, facts, reader):
    """Keep arbitrary autoloads and remove every analysis-only dispatch fact."""
    main = next(m for m in manifest['modules'] if m['module_id'] == -1)
    limit = facts['base'] + facts['main_size']
    for name in ('functions', 'labels', 'entry_points'):
        main[name] = [r for r in main.get(name, []) if facts['base'] <= int(r['addr']) < limit]
    if any(int(f['addr']) + int(f['size']) > limit for f in main['functions']):
        raise ValueError('enhanced analysis artifact overlaps a native function')
    main['calls'] = [r for r in main.get('calls', []) if int(r['from']) < limit and int(r['to']) < limit]
    for name in ('code_ranges', 'data_ranges'):
        main[name] = [[lo, min(hi, limit)] for lo, hi in main.get(name, []) if lo < limit]
    main['dispatch_regions'] = [r for r in main.get('dispatch_regions', []) if int(r['addr']) + int(r['size']) <= limit]
    for item in config.get('autoloads', []):
        kind = item.get('kind')
        if not isinstance(kind, dict) or 'Unknown' not in kind:
            continue
        index = int(kind['Unknown'])
        name = str(item.get('name', f'unk_autoload_{index}'))
        metadata = yaml.safe_load((images / f'unk_autoload_{index}.yaml').read_text())
        module = reader._module(Path(config['_directory']), item, -16 - index, name, int(metadata['base_address']))
        manifest['modules'].append(module)


def install_arm7(analyzer):
    if getattr(analyzer, '_decomp_four_word_autoload', False):
        return
    original = analyzer.parse_autoload_layout

    def parse(image, base):
        # A validated SDK-5 marker selects the four-word form. Older programs
        # keep the existing independently qualified three-word parser.
        sdk5 = any(struct.unpack_from('<3I', image, at) [1:] == (0xDEC00621, 0x2106C0DE)
                   and struct.unpack_from('<I', image, at)[0] >> 24 == 5
                   for at in range(24, min(len(image) - 11, 0x4000), 4))
        if not sdk5:
            return original(image, base)
        value = layout(image, base)
        blocks = tuple(analyzer.AutoloadBlock(a, size, bss, position, image[position:position + size])
                       for a, size, init, bss, position in value.blocks)
        return analyzer.AutoloadLayout(value.params, value.list_start, value.list_end, value.source,
                                       blocks, value.bss_start, value.bss_end)

    analyzer.parse_autoload_layout = parse
    analyzer._decomp_four_word_autoload = True
