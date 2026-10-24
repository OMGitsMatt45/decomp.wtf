"""Bounded streaming inspection of an owner's PS2 disc and boot executable.

No matching compiler, BIOS, emitter or optional runtime is installed or run by
inspection. A valid layout is preparation evidence, not a playable PC export.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import struct

from ..pc import PCError
from ..rom.errors import RomError
from ..rom.psx import _Disc, region_of

MAX_PROGRAM = 32 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_DIRECTORIES = 4096
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024


def _hash(stream):
    stream.seek(0)
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def _ram(address, size):
    if 0x70000000 <= address < 0x70004000:
        if size > 0x70004000 - address: raise PCError('PS2 ELF segment exceeds scratchpad')
        return 'scratchpad', address - 0x70000000
    physical = address & 0x1FFFFFFF
    if address >> 29 not in (0, 1, 4, 5) or physical >= 0x02000000 or size > 0x02000000 - physical:
        raise PCError('PS2 ELF segment exceeds EE RAM')
    return 'ee-ram', physical


def elf_info(data: bytes, *, boot_name: str = '') -> dict:
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise PCError('expected an ELF32 little-endian PS2 EE executable')
    kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shnames = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
    if kind != 2 or machine != 8 or version != 1 or ehsize != 52:
        raise PCError('expected an executable MIPS ELF; IOP modules are separate from the EE boot program')
    if not 0 < phnum <= 256 or phsize != 32 or phoff < ehsize or phoff + phnum * phsize > len(data):
        raise PCError('PS2 ELF program-header table is invalid or truncated')
    if shnum and (shnum > 8192 or shsize != 40 or shoff < ehsize or shoff + shnum * shsize > len(data) or shnames >= shnum):
        raise PCError('PS2 ELF section-header table is invalid or truncated')
    loads = []
    for index in range(phnum):
        ptype, offset, address, physical_address, filesz, memsz, pflags, alignment = struct.unpack_from('<8I', data, phoff + index * phsize)
        if ptype != 1: continue
        if filesz > memsz or offset > len(data) or filesz > len(data) - offset:
            raise PCError('PS2 ELF load segment exceeds its original file')
        if not memsz: continue
        region, physical = _ram(address, memsz)
        if alignment > 1 and (alignment & (alignment - 1) or address % alignment != offset % alignment):
            raise PCError('PS2 ELF load-segment alignment is invalid')
        loads.append(dict(index=index, offset=offset, address=address, physical_address=physical_address,
            region=region, physical=physical, file_size=filesz, memory_size=memsz, flags=pflags,
            sha256=hashlib.sha256(data[offset:offset + filesz]).hexdigest()))
    # Stripped retail programs can contain overlapping, zero-sized file loads
    # for BSS. Preserve them in order; do not mistake them for duplicate code.
    if entry & 3 or not any(s['flags'] & 1 and s['address'] <= entry < s['address'] + s['file_size'] for s in loads):
        raise PCError('PS2 ELF entry is not in file-backed executable code')
    symbols = 0
    executable_sections = []
    for index in range(shnum):
        _, stype, sflags, address, offset, size, _, _, _, entsize = struct.unpack_from('<10I', data, shoff + index * shsize)
        if stype != 8 and (offset > len(data) or size > len(data) - offset):
            raise PCError('PS2 ELF section exceeds its original file')
        if stype == 2 and size:
            if entsize != 16 or size % entsize: raise PCError('PS2 ELF symbol table has an invalid entry size')
            symbols += size // entsize
        if sflags & 4 and stype != 8 and size:
            executable_sections.append(dict(index=index, address=address, size=size, offset=offset))
    overlaps = []
    for n, right in enumerate(loads):
        for left in loads[:n]:
            if left['region'] == right['region'] and max(left['physical'], right['physical']) < min(left['physical'] + left['memory_size'], right['physical'] + right['memory_size']):
                overlaps.append(dict(first=left['index'], second=right['index'],
                    includes_file_bytes=bool(left['file_size'] and right['file_size'])))
    serial = re.match(r'^([A-Z]{4})[_-](\d{3})\.(\d{2})$', Path(boot_name).name.upper())
    code = f'{serial[1]}-{serial[2]}{serial[3]}' if serial else ''
    return dict(boot=boot_name, game_code=code, region=region_of(code), size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), entry=entry, flags=flags,
        ee_machine_flag=(flags & 0x00FF0000) == 0x00920000,
        symbols=symbols, stripped=not symbols, loads=loads, overlapping_loads=overlaps,
        executable_sections=executable_sections)


def mwo3_info(data: bytes) -> dict:
    """Metrowerks overlays describe their own addresses; no title table needed."""
    if len(data) < 64 or data[:4] != b'MWo3': raise PCError('expected a complete MWo3 overlay header')
    module_id, load, text_size, data_size, bss_size, ctor_begin, ctor_end = struct.unpack_from('<7I', data, 4)
    if load & 3 or text_size & 3 or not text_size or len(data) != 64 + text_size + data_size:
        raise PCError('MWo3 overlay code alignment or file size differs from its header')
    region, physical = _ram(load, len(data) + bss_size)
    if region != 'ee-ram': raise PCError('MWo3 overlay does not fit EE RAM')
    constructors = []
    if ctor_begin or ctor_end:
        if (ctor_begin & 3 or ctor_end & 3 or not load + 64 <= ctor_begin <= ctor_end <= load + len(data)):
            raise PCError('MWo3 constructor table exceeds its file-backed image')
        for offset in range(ctor_begin - load, ctor_end - load, 4):
            address = struct.unpack_from('<I', data, offset)[0]
            if address not in (0, 0xFFFFFFFF):
                if address & 3: raise PCError('MWo3 constructor pointer is unaligned')
                _ram(address, 4)
            constructors.append(address)
    name = data[32:64].split(b'\0', 1)[0].decode('ascii')
    if any(ord(c) < 32 for c in name): raise PCError('MWo3 overlay name contains control characters')
    return dict(format='MWo3', id=module_id, name=name, load_address=load, physical=physical,
        text_address=load + 64, text_size=text_size, data_size=data_size, bss_size=bss_size,
        memory_size=len(data) + bss_size, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        constructor_begin=ctor_begin, constructor_end=ctor_end, constructors=constructors)


def _both(raw, offset, width, field):
    a = int.from_bytes(raw[offset:offset + width], 'little')
    b = int.from_bytes(raw[offset + width:offset + 2 * width], 'big')
    if a != b: raise PCError('PS2 disc endian fields disagree: ' + field)
    return a


def _inventory(disc):
    pvd = disc.sector(16)
    if pvd[:7] != b'\x01CD001\x01' or _both(pvd, 128, 2, 'block size') != 2048:
        raise PCError('PS2 disc needs a valid ISO 9660 primary volume with 2048-byte data blocks')
    blocks = _both(pvd, 80, 4, 'volume size')
    if not blocks or blocks * disc.size > disc.length:
        raise PCError('PS2 disc declared volume exceeds its image')
    root = (_both(pvd, 158, 4, 'root extent'), _both(pvd, 166, 4, 'root size'))
    stack = [('', *root, frozenset(), 0)]
    entries, paths, directories, directory_bytes = [], set(), 0, 0
    while stack:
        prefix, lba, size, ancestors, depth = stack.pop()
        extent = lba, size
        if extent in ancestors: raise PCError('PS2 disc contains a cyclic directory')
        directories += 1; directory_bytes += size
        if directories > MAX_DIRECTORIES or directory_bytes > MAX_DIRECTORY_BYTES or depth > 32:
            raise PCError('PS2 disc directory inventory exceeds its supported bound')
        if lba * 2048 + size > blocks * 2048: raise PCError('PS2 directory exceeds the declared volume')
        for rec in disc.records(lba, size):
            name = rec['path']
            if name in ('.', '..') or any(ord(c) < 32 or c in '/\\' for c in name):
                raise PCError('PS2 disc has an unsafe ISO filename')
            if rec['extended_attributes'] or rec['unit'] or rec['gap'] or rec['flags'] & 0x80 or rec['volume'] != 1:
                raise PCError('PS2 extended-attribute, interleaved, multi-extent or multi-volume files need separate layout support')
            rec['path'] = prefix + name
            if rec['path'] in paths: raise PCError('PS2 disc has duplicate normalized paths')
            if rec['lba'] * 2048 + rec['size'] > blocks * 2048:
                raise PCError('PS2 file extent exceeds the declared volume')
            paths.add(rec['path']); entries.append(rec)
            if len(entries) > MAX_ENTRIES: raise PCError('PS2 disc has too many file records')
            if rec['directory']:
                stack.append((rec['path'] + '/', rec['lba'], rec['size'], ancestors | {extent}, depth + 1))
    return entries, blocks


def inspect(path: Path, *, hash_input: bool = True) -> dict:
    path = Path(path)
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            head = stream.read(52)
            if head[:4] == b'\x7fELF':
                if before.st_size > MAX_PROGRAM: raise PCError('PS2 EE program exceeds the supported 32 MiB input bound')
                stream.seek(0); raw = stream.read()
                program = elf_info(raw, boot_name=path.name)
                result = dict(input_kind='ee-elf', program=program, files=[])
            else:
                disc = _Disc(stream)
                entries, blocks = _inventory(disc)
                files = {e['path']: e for e in entries if not e['directory']}
                def read(name, limit):
                    rec = files.get(name)
                    if rec is None: raise PCError('PS2 disc is missing ' + name)
                    if rec['size'] > limit: raise PCError('PS2 file exceeds its inspection bound: ' + name)
                    return disc.read(rec['lba'], rec['size'])
                cnf = read('SYSTEM.CNF', 64 * 1024)
                boot = re.search(rb'^\s*BOOT2\s*=\s*cdrom0?:[\\/]+([^\r\n;]+)(?:;1)?\s*$', cnf, re.I | re.M)
                if not boot: raise PCError('this disc does not declare a PS2 BOOT2 executable')
                name = boot[1].decode('ascii').strip().replace('\\', '/').upper()
                if any(part in ('', '.', '..') for part in name.split('/')):
                    raise PCError('PS2 BOOT2 path is invalid')
                program = elf_info(read(name, MAX_PROGRAM), boot_name=name)
                overlays = []
                for rec in entries:
                    if rec['directory']: continue
                    header = disc.read(rec['lba'], min(rec['size'], 64))
                    if header[:4] == b'\x7fELF':
                        rec['elf_type'] = int.from_bytes(header[16:18], 'little')
                        rec['role'] = 'iop-irx' if rec['elf_type'] in (0xFF80, 0xFF81) else 'ee-elf' if rec['path'] == name else 'elf-module'
                    elif header[:4] == b'MWo3':
                        overlay = mwo3_info(read(rec['path'], MAX_PROGRAM))
                        overlay['path'] = rec['path']
                        overlay['elf_reservations'] = [s['index'] for s in program['loads']
                            if not s['file_size'] and s['region'] == 'ee-ram' and
                            s['physical'] == overlay['physical'] and s['memory_size'] == overlay['memory_size']]
                        overlays.append(overlay); rec['role'] = 'ee-overlay'; rec['overlay_format'] = 'MWo3'
                result = dict(input_kind='disc', sector_size=disc.size, sector_data_offset=disc.skip,
                    volume_blocks=blocks, program=program, files=entries,
                    overlays=overlays,
                    iop_modules=[e['path'] for e in entries if e.get('role') == 'iop-irx'])
            digest = _hash(stream) if hash_input else None
            after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise PCError('PS2 input changed during inspection')
            current = path.stat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                raise PCError('PS2 input changed during inspection')
    except (RomError, UnicodeError, struct.error) as error:
        raise PCError(str(error)) from error
    return dict(schema='decomp.wtf.ps2-input/v1', platform='ps2',
        input=dict(name=path.name, size=before.st_size, sha256=digest, identity_verified=hash_input),
        native_game_qualified=False, app_backend_registered=False, **result)
