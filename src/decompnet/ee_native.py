"""Assemble native EE hosts from verified PE templates and the pinned archive.

Published templates contain no compiler payload. Installation inserts the exact
upstream ELF bytes into a dedicated read-only PE section; no compiler is rebuilt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct

ARCHIVE_SHA256 = '0590d2ca9da8f5903889d66761220d14b47a8d14ba987ca53db84a1650a1fd0a'
PROGRAMS = ('bin/ee-gcc', 'bin/ee-as', 'lib/gcc-lib/ee/2.96-ee-001003-1/cc1',
            'lib/gcc-lib/ee/2.96-ee-001003-1/cc1plus', 'lib/gcc-lib/ee/2.96-ee-001003-1/cpp0')
ALIASES = {'ee/bin/as': 'bin/ee-as', 'bin/ee-g++': 'bin/ee-gcc', 'bin/ee-cpp': 'bin/ee-gcc'}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_section(executable: bytes) -> tuple[int, int]:
    if executable[:2] != b'MZ' or len(executable) < 64:
        raise ValueError('EE host is not a PE executable')
    pe = struct.unpack_from('<I', executable, 60)[0]
    if executable[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Invalid EE host PE header')
    machine, count = struct.unpack_from('<HH', executable, pe + 4)
    optional_size = struct.unpack_from('<H', executable, pe + 20)[0]
    if machine != 0x14c:
        raise ValueError('EE host must be an i386 PE')
    sections = pe + 24 + optional_size
    matches = []
    for index in range(count):
        section = sections + 40 * index
        name, size, address, raw_size, offset = struct.unpack_from('<8sIIII', executable, section)
        if name.rstrip(b'\0') == b'.eepay':
            if size > raw_size or offset + raw_size > len(executable):
                raise ValueError('Truncated EE payload section')
            matches.append((offset, size))
    if len(matches) != 1:
        raise ValueError('EE host requires one payload section')
    return matches[0]


def materialize(root: Path) -> None:
    manifest = json.loads((root / 'host-templates.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or manifest.get('archive_sha256') != ARCHIVE_SHA256 \
            or set(manifest.get('tools', {})) != set(PROGRAMS):
        raise ValueError('EE templates do not identify the pinned compiler')
    # Validate every input before modifying any executable.
    images = {}
    for name in PROGRAMS:
        record = manifest['tools'][name]
        payload = (root / name).read_bytes()
        template = (root / (name + '.exe')).read_bytes()
        offset, size = payload_section(template)
        if payload[:6] != b'\x7fELF\x01\x01' or sha256(payload) != record['payload_sha256'] \
                or sha256(template) != record['template_sha256'] or size != len(payload) \
                or any(template[offset:offset + size]):
            raise ValueError(f'Invalid EE template or original compiler: {name}')
        image = template[:offset] + payload + template[offset + size:]
        if sha256(image) != record['executable_sha256']:
            raise ValueError(f'EE executable checksum mismatch: {name}')
        images[name] = image
    for name, image in images.items():
        (root / (name + '.exe')).write_bytes(image)
    for alias, name in ALIASES.items():
        target = root / (alias + '.exe')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / (name + '.exe'), target)
    (root / 'host-templates.json').unlink()
