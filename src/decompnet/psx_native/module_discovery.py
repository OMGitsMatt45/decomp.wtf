"""Read additional disc programs and address-bearing HBD memory images.

Discover code roots from the input bytes. No title profile, runtime trace or
current-disc assumption identifies the code that an emitted module may execute.
"""
import hashlib
import struct
from collections import OrderedDict

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

from .. import pc
from ..rom import psx, psx_hbd
from ..rom.errors import RomError

MAX_MODULES = 4096
MAX_IMAGE_BYTES = 128 << 20


def _word(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _control(word):
    op = word >> 26
    return (op in (1, 2, 3, 4, 5, 6, 7) or
            op == 0 and (word & 63) in (8, 9, 12, 13) or
            op in (16, 17, 18, 19) and (word >> 21 & 31) == 8)


def code_roots(data, load):
    """Framed functions and bounded return-proven leaves, including callbacks."""
    roots = set()
    for offset in range(0, len(data)-7, 4):
        word = _word(data, offset)
        if word >> 16 != 0x27bd or not word & 0x8000:
            continue
        frame = 0x10000 - (word & 0xffff)
        if frame & 3 or not 4 <= frame <= 4096:
            continue
        for at in range(offset+4, min(offset+64, len(data)-3), 4):
            following = _word(data, at)
            if following >> 16 == 0xafbf and (following & 0xffff) <= frame-4:
                roots.add(load+offset)
                break
            if _control(following):
                break

    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    checked = set()

    def leaf(address):
        offset = address-load
        if address in checked or offset & 3 or not 0 <= offset <= len(data)-8:
            return
        checked.add(address)
        # A pointer or a previous return establishes the entry boundary; still
        # require the whole leaf and its delay slot to decode before accepting it.
        instructions = list(decoder.disasm(data[offset:offset+132], address, count=33))
        for index, instruction in enumerate(instructions[:32]):
            if instruction.address != address+index*4 or instruction.size != 4:
                return
            word = _word(data, offset+index*4)
            if word == 0x03e00008:
                if index+1 < len(instructions) and not _control(_word(data, offset+(index+1)*4)):
                    roots.add(address)
                return
            if _control(word):
                return

    # Packed command records can contain an unaligned stored pointer, while the
    # MIPS instruction it names must remain word-aligned.
    for offset in range(len(data)-3):
        pointer = _word(data, offset)
        if pointer >> 28 in (8, 10):
            pointer = 0x80000000 | (pointer & 0x1fffffff)
            if not pointer & 3 and load <= pointer < load+len(data):
                leaf(pointer)
    for offset in range(0, len(data)-11, 4):
        if _word(data, offset) != 0x03e00008:
            continue
        at = offset+8
        for _ in range(6):
            if at+4 > len(data) or _word(data, at):
                break
            at += 4
        leaf(load+at)
    return sorted(roots)


def _files(disc):
    pvd = disc.sector(16)
    pending = [('', struct.unpack_from('<I', pvd, 158)[0], struct.unpack_from('<I', pvd, 166)[0])]
    seen = set()
    while pending:
        parent, lba, size = pending.pop()
        if (lba, size) in seen:
            continue
        seen.add((lba, size))
        for record in disc.records(lba, size):
            if record['extended_attributes'] or record['unit'] or record['gap'] or record['flags'] & 0x80:
                continue
            name = parent+record['path']
            if record['directory']:
                pending.append((name+'/', record['lba'], record['size']))
            else:
                yield dict(record, path=name)


def _reader(disc, record):
    cache = OrderedDict()

    def read(offset, count):
        if offset < 0 or count < 0 or offset+count > record['size']:
            raise RomError('embedded PS1 program exceeds its original file extent')
        sector, skip = divmod(offset, 2048)
        if count+skip > 2048:
            return disc.read(record['lba']+sector, count+skip)[skip:]
        if sector not in cache:
            cache[sector] = disc.sector(record['lba']+sector)
            if len(cache) > 32:
                cache.popitem(last=False)
        return cache[sector][skip:skip+count]
    return read


def memory_image(data, load, source):
    """Wrap a bounded, address-bearing memory image for the pinned translator."""
    physical = load & 0x1fffffff
    if load >> 28 not in (8, 10) or load & 3 or not data or physical+len(data) > 0x200000:
        return None
    load = 0x80000000 | physical
    roots = code_roots(data, load)
    if not roots:
        return None
    header = bytearray(2048)
    header[:8] = b'PS-X EXE'
    struct.pack_into('<4I', header, 0x10, roots[0], 0, load, len(data))
    image, info = psx.read_exe(bytes(header)+data, 'EMBEDDED.EXE')
    info['native_entries'] = roots
    return dict(image=image, info=info, source=source)


def discover(stream, boot_image):
    disc = psx._Disc(stream)
    modules = []
    seen = {hashlib.sha256(boot_image).hexdigest()}
    seen_memory = set()
    image_bytes = 0

    def append(module):
        nonlocal image_bytes
        key = hashlib.sha256(module['image']).hexdigest()
        if key in seen:
            return
        if len(modules) >= MAX_MODULES or image_bytes+len(module['image']) > MAX_IMAGE_BYTES:
            raise pc.PCError('embedded PS1 programs exceed the bounded source-generation catalog')
        seen.add(key)
        image_bytes += len(module['image'])
        module['boot'] = f'PROGRAM_{len(modules)+1}.EXE'
        modules.append(module)

    for record in _files(disc):
        if record['size'] < 8:
            continue
        read = _reader(disc, record)
        if read(0, 8) == b'PS-X EXE':
            # Only the declared RAM image is executable. A file trailer is
            # retained on the disc, without reading it into the code catalog.
            header = read(0, min(2048, record['size']))
            if len(header) < 2048:
                raise RomError('truncated embedded PS1 executable header')
            size = _word(header, 0x1c)
            if size > 0x200000 or 2048+size > record['size']:
                raise RomError('embedded PS1 executable exceeds its RAM image or file extent')
            image, info = psx.read_exe(header+read(2048, size), record['path'])
            append(dict(image=image, info=info, source=dict(format='iso-program', path=record['path'])))
            continue
        if record['size'] % 2048 or record['size'] > 1 << 30:
            continue
        try:
            inventory = psx_hbd.inventory(read, record['size'])
        except RomError:
            # Other resources need not be HBD archives. Ambiguous candidate
            # containers cannot establish a memory image and remain uncompiled.
            continue
        for block in inventory['blocks']:
            for member in block['members']:
                load = member['unknown']
                if (member['type'] != 31 or member['codec'] not in ('raw', 'hbd-lzss') or
                        load >> 28 not in (8, 10) or load & 3 or
                        (load & 0x1fffffff)+member['size'] > 0x200000):
                    continue
                data = psx_hbd.decoded(read, member)
                key = (load & 0x1fffffff, hashlib.sha256(data).digest())
                if key in seen_memory:
                    continue
                seen_memory.add(key)
                source = dict(format='hbd-memory', path=record['path'], sector=block['sector'],
                              member=member['index'], allocation=member['size'])
                module = memory_image(data, load, source)
                if module is not None:
                    append(module)
    return modules
