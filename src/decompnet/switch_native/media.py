"""Bounded NSO/NRO image loading, ported from Kirikae's MIT loader.

Kirikae commit 726c4a1bc6fd9a52a22606894b80a903f4728e55:
crates/loader/src/{nso,nro,lz4}.rs. See MIT.Kirikae.txt.
Local changes: validate all ranges before allocation, segment overlap, NSO
hashes, LZ4 expansion bounds, exact input identity and explicit CPU-only scope.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from ..pc import PCError

BASE = 0x7100000000
MAX_FILE = 512 * 1024 * 1024
MAX_IMAGE = 256 * 1024 * 1024


def decompress(src: bytes, expected: int) -> bytes:
    """Raw LZ4 blocks, including overlapping matches; bound before expanding."""
    if not 0 <= expected <= MAX_IMAGE:
        raise PCError('Switch LZ4 output exceeds its bound')
    out = bytearray()
    at = 0

    def byte():
        nonlocal at
        if at >= len(src):
            raise PCError('truncated Switch LZ4 block')
        value = src[at]
        at += 1
        return value

    def length(nibble):
        count = nibble
        if nibble == 15:
            while True:
                value = byte()
                count += value
                if count > expected:
                    raise PCError('Switch LZ4 expansion exceeds its declared size')
                if value != 255:
                    break
        return count

    while at < len(src):
        token = byte()
        literals = length(token >> 4)
        if at + literals > len(src) or len(out) + literals > expected:
            raise PCError('invalid Switch LZ4 literal range')
        out.extend(src[at:at + literals])
        at += literals
        if at == len(src):
            break
        offset = byte() | byte() << 8
        if offset == 0 or offset > len(out):
            raise PCError('invalid Switch LZ4 match offset')
        count = length(token & 15) + 4
        if len(out) + count > expected:
            raise PCError('Switch LZ4 expansion exceeds its declared size')
        start = len(out) - offset
        for k in range(count):
            out.append(out[start + k])
    if len(out) != expected:
        raise PCError('Switch LZ4 output size differs')
    return bytes(out)


def load(path, *, include_image=False):
    path = Path(path)
    if not path.is_file() or not 0x80 <= path.stat().st_size <= MAX_FILE:
        raise PCError('Switch inspection requires an NSO/NRO module of 128 bytes to 512 MiB')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise PCError('Switch input exceeds 512 MiB')
    u32 = lambda at: struct.unpack_from('<I', raw, at)[0]
    if raw[:4] == b'NSO0':
        kind = 'nso'
        if len(raw) < 0x100 or u32(4) != 0:
            raise PCError('truncated or unsupported Switch NSO header')
        flags = u32(0x0c)
        if flags & ~0x3f:
            raise PCError('unsupported Switch NSO flags')
        bss = u32(0x3c)
        segments = []
        for i in range(3):
            off, memory, size = struct.unpack_from('<III', raw, 0x10 + 0x10 * i)
            compressed = bool(flags & (1 << i))
            stored = u32(0x60 + 4 * i) if compressed else size
            segments.append(dict(file_offset=off, offset=memory, size=size, stored=stored,
                compressed=compressed, check_hash=bool(flags & (8 << i)),
                expected_hash=raw[0xa0 + i * 32:0xc0 + i * 32].hex()))
        declared = len(raw)
    elif raw[0x10:0x14] == b'NRO0':
        kind = 'nro'
        declared = u32(0x18)
        if u32(0x14) != 0 or not 0x80 <= declared <= len(raw):
            raise PCError('invalid Switch NRO declared size or version')
        bss = u32(0x38)
        segments = []
        for i in range(3):
            off, size = struct.unpack_from('<II', raw, 0x20 + i * 8)
            segments.append(dict(file_offset=off, offset=off, size=size, stored=size,
                                 compressed=False, check_hash=False))
    else:
        raise PCError('Switch CPU development accepts extracted NSO or homebrew NRO modules')
    if segments[0]['offset'] != 0 or not segments[0]['size'] or segments[0]['size'] % 4:
        raise PCError('Switch text must start at zero and contain aligned AArch64 instructions')
    image_end = segments[2]['offset'] + segments[2]['size'] + bss
    if not 0 < image_end <= MAX_IMAGE:
        raise PCError('Switch memory image exceeds 256 MiB')
    live_file = []
    last_end = 0
    for segment in segments:
        off, size, memory, stored = (segment[k] for k in ('file_offset', 'size', 'offset', 'stored'))
        if memory % 4 or memory < last_end or memory + size > image_end:
            raise PCError('Switch memory segments overlap or exceed the image')
        if size and (off < (0x100 if kind == 'nso' else 0) or off + stored > declared or not stored):
            raise PCError('Switch segment exceeds the input or overlaps its header')
        if any(off < end and start < off + stored for start, end in live_file) and size:
            raise PCError('Switch file segments overlap')
        if size:
            live_file.append((off, off + stored))
        last_end = memory + size
    image = bytearray((image_end + 0xfff) & ~0xfff)
    for i, segment in enumerate(segments):
        off, stored, size = (segment[k] for k in ('file_offset', 'stored', 'size'))
        data = raw[off:off + stored] if size else b''
        if segment['compressed']:
            data = decompress(data, size)
        if len(data) != size:
            raise PCError('Switch segment size differs')
        if segment['check_hash'] and hashlib.sha256(data).hexdigest() != segment['expected_hash']:
            raise PCError('Switch NSO segment checksum differs')
        segment['sha256'] = hashlib.sha256(data).hexdigest()
        segment['name'] = ('text', 'rodata', 'data')[i]
        segment['access'] = ('rx', 'r', 'rw')[i]
        image[segment['offset']:segment['offset'] + size] = data
    # Nintendo's rodata module-path record can identify an NSS even when its
    # ELF dynamic table omits DT_SONAME. It is metadata, never a host path.
    module_name = None
    ro = segments[1]
    if kind == 'nso' and ro['size'] >= 9:
        start = ro['offset']
        marker, length = struct.unpack_from('<II', image, start)
        if marker == 0 and 0 < length <= min(1024, ro['size'] - 9) and image[start + 8 + length] == 0:
            try:
                candidate = image[start + 8:start + 8 + length].decode('utf-8')
                if candidate.isprintable() and '\x00' not in candidate:
                    module_name = candidate
            except UnicodeDecodeError:
                pass
    result = dict(platform='switch', format=kind, base=BASE, entry=BASE, module_name=module_name,
        build_id=raw[0x40:0x60].hex(), image_size=len(image), bss_size=bss,
        segments=segments, input=dict(name=path.name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        native_game_backend_available=False, scope='single-module-cpu-development')
    if include_image:
        result['image'] = bytes(image)
    return result
