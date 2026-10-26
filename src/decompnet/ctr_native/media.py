"""Bounded, read-only loading of decrypted 3DS NCCH/NCSD executables.

No console keys, firmware or external unpackers are used. Offsets are validated
before source generation. CIA installation, homebrew relocation and RomFS file
decoding are separate work; this loader retains their boundaries explicitly.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from ..pc import PCError

UNIT = 0x200
PAGE = 0x1000
MAX_CODE = 64 * 1024 * 1024
MAX_MEMORY = 128 * 1024 * 1024


def recognizable(head: bytes) -> bool:
    return head[0x100:0x104] in (b'NCCH', b'NCSD')


def _u32(raw, at):
    return struct.unpack_from('<I', raw, at)[0]


def _range(offset, size, end, what):
    if offset < 0 or size < 0 or offset > end or size > end - offset:
        raise PCError(f'3DS {what} exceeds its container')
    return offset, size


def decompress(raw: bytes, *, expected: int) -> bytes:
    """SDK backwards LZSS, bounded by the validated executable layout."""
    if len(raw) < 8:
        raise PCError('3DS compressed code has no BLZ footer')
    footer, extra = struct.unpack_from('<II', raw, len(raw)-8)
    header, span = footer >> 24, footer & 0xffffff
    size = len(raw) + extra
    if not 8 <= header <= span <= len(raw) or not 0 < size <= expected <= MAX_CODE:
        raise PCError('3DS BLZ footer or decompressed size is invalid')
    out = bytearray(size)
    out[:len(raw)] = raw
    source, stop, dest = len(raw)-header, len(raw)-span, size
    while source > stop and dest > stop:
        source -= 1
        flags = raw[source]
        for _ in range(8):
            if dest <= stop:
                break
            if flags & 0x80:
                if source-2 < stop:
                    raise PCError('3DS BLZ back-reference is truncated')
                source -= 2
                pair = int.from_bytes(raw[source:source+2], 'little')
                # Distance is measured from the destination byte after it is
                # decremented. The minimum backward-copy distance is three.
                count, distance = (pair >> 12)+3, (pair & 0xfff)+3
                if count > dest-stop:
                    raise PCError('3DS BLZ back-reference exceeds output')
                for _ in range(count):
                    dest -= 1
                    if dest+distance >= size:
                        raise PCError('3DS BLZ back-reference reads beyond output')
                    out[dest] = out[dest+distance]
            else:
                if source <= stop:
                    raise PCError('3DS BLZ literal is truncated')
                source -= 1
                dest -= 1
                out[dest] = raw[source]
            flags = (flags << 1) & 0xff
    if source != stop or dest != stop:
        raise PCError('3DS BLZ stream does not fill its declared output')
    return bytes(out)


def load(path: Path, *, include_code=False) -> dict:
    return load_source(Path(path), include_code=include_code)


def load_source(path, *, include_code=False) -> dict:
    """Inspect a seekable source with open/stat, including a streamed archive member.

    Reads remain bounded and the complete source is hashed. A source that
    decompresses on demand may restart its stream when seeking backwards;
    no full uncompressed image needs to be stored on disk.
    """
    size = path.stat().st_size
    with path.open('rb') as stream:
        def read(at, count, label, end=size):
            _range(at, count, min(size, end), label)
            stream.seek(at)
            raw = stream.read(count)
            if len(raw) != count:
                raise PCError('3DS input changed or was truncated during reading')
            return raw

        head = read(0, UNIT, 'header')
        partitions = []
        if head[0x100:0x104] == b'NCSD':
            for index in range(8):
                offset, length = struct.unpack_from('<II', head, 0x120+index*8)
                if not length:
                    if offset:
                        raise PCError('3DS NCSD empty partition has a nonzero offset')
                    continue
                offset, length = offset*UNIT, length*UNIT
                _range(offset, length, size, 'NCSD partition')
                if offset < UNIT or any(offset < p['offset']+p['size'] and p['offset'] < offset+length for p in partitions):
                    raise PCError('3DS NCSD partitions overlap')
                partitions.append(dict(index=index, offset=offset, size=length))
            first = next((p for p in partitions if p['index'] == 0), None)
            if first is None:
                raise PCError('3DS NCSD has no executable partition 0')
            base, limit = first['offset'], first['offset']+first['size']
            head = read(base, UNIT, 'NCCH header', limit)
            kind = 'ncsd'
        elif head[0x100:0x104] == b'NCCH':
            base, limit, kind = 0, size, 'ncch'
        else:
            raise PCError('3DS development currently accepts decrypted NCCH/CXI or NCSD/CCI/.3ds images; CIA and 3DSX are not implemented')
        if head[0x100:0x104] != b'NCCH':
            raise PCError('3DS executable partition has no NCCH header')
        declared = _u32(head, 0x104)*UNIT
        if declared < 0x600:
            raise PCError('3DS NCCH declared size is too small')
        _range(base, declared, limit, 'NCCH declared image')
        limit = base+declared
        if not head[0x18f] & 4:
            raise PCError('3DS NCCH is encrypted or not marked decrypted; supply a decrypted dump (no keys or BIOS are required by this loader)')
        if _u32(head, 0x180) != 0x400:
            raise PCError('3DS executable requires a 0x400-byte extended header')
        ex = read(base+UNIT, 0x400, 'extended header', limit)
        segments = []
        for name, at, access in (('text', 0x10, 'rx'), ('rodata', 0x20, 'r'), ('data', 0x30, 'rw')):
            address, pages, length = struct.unpack_from('<III', ex, at)
            allocated = pages*PAGE
            if allocated > MAX_MEMORY or length > allocated or address % PAGE or address+allocated > 0x10000000:
                raise PCError('3DS executable segment layout is invalid: '+name)
            if length and address < 0x100000:
                raise PCError('3DS executable segment is below application memory')
            if allocated and any(address < s['address']+s['allocated'] and s['address'] < address+allocated for s in segments if s['allocated']):
                raise PCError('3DS executable segments overlap')
            segments.append(dict(name=name, address=address, allocated=allocated, size=length, access=access))
        bss = _u32(ex, 0x3c)
        total = sum(s['allocated'] for s in segments)
        for segment in segments:
            segment['memory_size'] = max(segment['allocated'], ((segment['size']+bss+PAGE-1)//PAGE)*PAGE) if segment['name']=='data' else segment['allocated']
            if segment['address']+segment['memory_size'] > 0x0fff0000:
                raise PCError('3DS executable overlaps the CPU probe stack reservation')
        if not segments[0]['size'] or sum(s['memory_size'] for s in segments) > MAX_MEMORY:
            raise PCError('3DS executable code/BSS exceeds its memory bound')
        data = segments[-1]
        if data['memory_size'] and any(s['memory_size'] and data['address'] < s['address']+s['memory_size'] and s['address'] < data['address']+data['memory_size'] for s in segments[:-1]):
            raise PCError('3DS executable BSS overlaps another segment')
        code_limit = segments[0]['allocated']+segments[1]['allocated']+segments[2]['size']
        if not 0 < code_limit <= MAX_CODE:
            raise PCError('3DS executable code size exceeds its bound')
        sections = []
        for name, at in (('plain', 0x190), ('logo', 0x198), ('exefs', 0x1a0), ('romfs', 0x1b0)):
            offset, length = struct.unpack_from('<II', head, at)
            if not length:
                continue
            offset, length = base+offset*UNIT, length*UNIT
            _range(offset, length, limit, name)
            if offset < base+0x600 or any(offset < s['offset']+s['size'] and s['offset'] < offset+length for s in sections):
                raise PCError('3DS NCCH sections overlap headers or one another')
            sections.append(dict(name=name, offset=offset, size=length))
        exefs = next((s for s in sections if s['name']=='exefs'), None)
        if exefs is None or exefs['size'] < UNIT:
            raise PCError('3DS executable has no ExeFS')
        table = read(exefs['offset'], UNIT, 'ExeFS header', limit)
        files = []
        for index in range(10):
            name = table[index*16:index*16+8].split(b'\0')[0]
            offset, length = struct.unpack_from('<II', table, index*16+8)
            if not name:
                if offset or length:
                    raise PCError('3DS empty ExeFS entry contains a payload')
                continue
            try:
                name = name.decode('ascii')
            except UnicodeDecodeError as error:
                raise PCError('3DS ExeFS name is not ASCII') from error
            _range(UNIT+offset, length, exefs['size'], 'ExeFS file')
            absolute = exefs['offset']+UNIT+offset
            if any(name==f['name'] or absolute < f['offset']+f['size'] and f['offset'] < absolute+length for f in files):
                raise PCError('3DS ExeFS files overlap or repeat a name')
            files.append(dict(name=name, offset=absolute, size=length,
                              sha256=table[0x200-(index+1)*32:0x200-index*32].hex()))
        item = next((f for f in files if f['name']=='.code'), None)
        if item is None or not 0 < item['size'] <= MAX_CODE:
            raise PCError('3DS ExeFS has no bounded .code file')
        raw = read(item['offset'], item['size'], '.code', limit)
        checksum = hashlib.sha256(raw).hexdigest()
        if item['sha256'] != checksum:
            raise PCError('3DS ExeFS .code checksum differs from its header')
        # SDK BLZ output may include the padding at the end of the data page.
        # Bound it by the complete allocation, while retaining the absolute cap.
        code = decompress(raw, expected=min(total, MAX_CODE)) if ex[0xd] & 1 else raw
        cursor = 0
        for segment in segments:
            if cursor+segment['size'] > len(code):
                raise PCError('3DS .code is shorter than the extended-header layout')
            segment['code_offset'] = cursor
            cursor += segment['allocated']
        if len(code) > total:
            raise PCError('3DS .code exceeds the extended-header allocation')
        stream.seek(0)
        identity = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != size:
            raise PCError('3DS input changed during inspection')
        result = dict(platform='3ds', format=kind, title=ex[:8].split(b'\0')[0].decode('ascii', 'replace'),
                      program_id=f'{int.from_bytes(head[0x118:0x120], "little"):016x}',
                      input=dict(size=size, sha256=identity), entry=segments[0]['address'],
                      segments=segments, bss_size=bss, partitions=partitions, sections=sections, exefs=files,
                      compressed=bool(ex[0xd] & 1), code_sha256=hashlib.sha256(code).hexdigest(),
                      native_game_backend_available=True, retail_qualified=False)
        if include_code:
            result['code'] = code
        return result
