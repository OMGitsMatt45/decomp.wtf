"""Format-driven module adapters; no game names, addresses or function maps.

MWo3 ELF wrappers preserve the entire original load image, including its header.
Their entry points mark text for analysis, not a standalone game boot contract.
Only the declared text is executable; data and BSS must not become EE code.
"""
from __future__ import annotations

import struct

from .media import mwo3_info


def mwo3_elf(image: bytes) -> bytes:
    info = mwo3_info(image)
    load, text, text_size = info['load_address'], info['text_address'], info['text_size']
    offset = 0x100
    wrapped = bytearray(offset) + image
    names = b'\0.mwo3\0.text\0.data\0.bss\0.shstrtab\0'
    names_offset = len(wrapped)
    wrapped.extend(names)
    wrapped.extend(bytes(-len(wrapped) % 4))
    sections_offset = len(wrapped)
    sections = [bytes(40)]
    for name, kind, flags, address, file_offset, size, alignment in (
        ('.mwo3', 1, 2, load, offset, 64, 4),
        ('.text', 1, 6, text, offset + 64, text_size, 4),
        ('.data', 1, 3, text + text_size, offset + 64 + text_size, info['data_size'], 1),
        ('.bss', 8, 3, load + len(image), offset + len(image), info['bss_size'], 1),
        ('.shstrtab', 3, 0, 0, names_offset, len(names), 1),
    ):
        sections.append(struct.pack('<10I', names.index(name.encode() + b'\0'), kind,
            flags, address, file_offset, size, 0, 0, alignment, 0))
    wrapped.extend(b''.join(sections))
    struct.pack_into('<16sHHIIIIIHHHHHH', wrapped, 0,
        b'\x7fELF\x01\x01\x01' + bytes(9), 2, 8, 1, text, 52,
        sections_offset, 0x20924001, 52, 32, 1, 40, len(sections), 5)
    # One load preserves the exact original bytes and separate BSS extent.
    # Byte alignment accommodates all valid header-derived virtual aliases.
    struct.pack_into('<8I', wrapped, 52, 1, offset, load, load, len(image),
        info['memory_size'], 7, 1)
    return bytes(wrapped)
