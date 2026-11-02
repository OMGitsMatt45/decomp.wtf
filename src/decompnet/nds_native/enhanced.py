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
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from capstone.arm_const import ARM_OP_MEM, ARM_REG_PC

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


def startup_tail(image, base, entry, limit):
    """Retain the real startup's declared literal tail target for DSD's main root."""
    decoder = Cs(CS_ARCH_ARM, CS_MODE_ARM); decoder.detail = True
    instructions = []
    for instruction in decoder.disasm(image[entry-base:min(len(image),entry-base+0x800)],entry):
        if instruction.mnemonic == 'bx':
            register = instruction.operands[0].reg
            for previous in reversed(instructions):
                if register not in previous.regs_access()[1]:
                    continue
                if previous.mnemonic != 'ldr' or previous.operands[0].reg != register:
                    break
                memory = previous.operands[1]
                if memory.type != ARM_OP_MEM or memory.mem.base != ARM_REG_PC or memory.mem.index:
                    break
                literal = previous.address + 8 + memory.mem.disp - base
                if not 0 <= literal <= len(image)-4:
                    break
                target = struct.unpack_from('<I',image,literal)[0]
                if base <= (target & ~1) < limit:
                    return target
                break
            break
        instructions.append(instruction)
    return entry


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
    padding = 64
    native_main = startup_tail(original,main.address,entry,info.source)
    canonical = bytearray(original[:split] + bytes(padding) + original[split:])
    for index, (address, size, init, bss, position) in enumerate(info.blocks):
        struct.pack_into('<3I', canonical, info.list_start - main.address + padding + 12 * index, address, size, bss)
    struct.pack_into('<4I', canonical, info.params, info.list_start + padding,
                     info.list_start + padding + 12 * len(info.blocks), info.source + padding, info.source + padding)
    struct.pack_into('<I', canonical, info.params + 20, 0)
    # A decoder-only NTR entry has a conventional empty ctor runner and a
    # literal tail target naming the original startup. No game code is patched.
    wrapper = info.source
    original_call = 0xEB000000 | (((entry - wrapper - 8) // 4) & 0xFFFFFF)
    struct.pack_into('<5I', canonical, split, original_call, 0xEB000005, 0xE59F3000, 0xE12FFF13,native_main)
    struct.pack_into('<4I', canonical, split + 32, 0xE59F0000, 0xE12FFF1E, wrapper + 44, 0)
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
    return dict(main_size=split, analysis_padding=padding, base=main.address, entry=entry,
                native_main=native_main, params=info.params,
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


def prepare_extracted(extracted, facts):
    """Satisfy required decoder TCM fields without relabelling native regions."""
    arm9 = extracted / 'arm9'
    config_path = extracted / 'config.yaml'
    config = yaml.safe_load(config_path.read_text())
    facts['synthetic_tcms'] = []
    for name, base, kind in [('itcm', 0x01FF8000, 'Itcm'), ('dtcm', 0x027E0000, 'Dtcm')]:
        if not (arm9 / (name + '.bin')).exists():
            (arm9 / (name + '.bin')).write_bytes(bytes(32))
            (arm9 / (name + '.yaml')).write_text(yaml.safe_dump(dict(
                base_address=base, code_size=32, bss_size=0, kind=kind)), encoding='utf-8')
            facts['synthetic_tcms'].append(name)
    # The dependency sorts ITCM, DTCM, then arbitrary autoloads on reload;
    # their analysis indexes must describe that order, including placeholders.
    facts['analysis_autoloads'] = []
    native = {item['address']: item for item in facts['autoloads']}
    for index, item in enumerate(config.get('unknown_autoloads', []), 2):
        metadata = yaml.safe_load((extracted / item['config']).read_text())
        original = native.get(int(metadata['base_address']))
        if original is None or original['size'] != metadata['code_size']:
            raise ValueError('enhanced extracted autoload differs from validated native layout')
        item['index'] = index
        metadata['kind'] = {'Unknown': index}
        (extracted / item['config']).write_text(yaml.safe_dump(metadata), encoding='utf-8')
        facts['analysis_autoloads'].append({**item, 'native_index': original['index']})
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')


def restore_images(extracted, images, facts):
    """Remove the synthetic entry and restore original mutable parameter words."""
    for path in {extracted / 'arm9/arm9.bin', images / 'arm9.bin'}:
        data = bytearray(path.read_bytes())
        if len(data) != facts['main_size'] + facts['analysis_padding']:
            raise ValueError('enhanced decoder changed the expected static analysis extent')
        data = data[:facts['main_size']]
        at = facts['params']
        data[at:at + 24] = bytes.fromhex(facts['parameter_hex'])
        path.write_bytes(data)
    for item in facts.get('analysis_autoloads', []):
        name = 'autoload_' + str(item['index'])
        shutil.copyfile(extracted / item['bin'], images / (name + '.bin'))
        shutil.copyfile(extracted / item['config'], images / (name + '.yaml'))


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
    manifest['modules'] = [m for m in manifest['modules'] if m['name'] not in facts.get('synthetic_tcms', [])]
    indexes = {item['index']: item['native_index'] for item in facts.get('analysis_autoloads', [])}
    for item in config.get('autoloads', []):
        kind = item.get('kind')
        if not isinstance(kind, dict) or 'Unknown' not in kind:
            continue
        index = int(kind['Unknown'])
        name = str(item.get('name', f'unk_autoload_{index}'))
        metadata = yaml.safe_load((images / f'autoload_{index}.yaml').read_text())
        module = reader._module(Path(config['_directory']), item, -16 - indexes[index], name, int(metadata['base_address']))
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
