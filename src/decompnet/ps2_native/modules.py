"""Format-driven module adapters; no game names, addresses or function maps.

MWo3 ELF wrappers preserve the entire original load image, including its header.
Their entry points mark text for analysis, not a standalone game boot contract.
Only the declared text is executable; data and BSS must not become EE code.
"""
from __future__ import annotations

import struct

from ..pc import PCError
from .media import MAX_PROGRAM, elf_info, mwo3_info


def typed_elf(original: bytes, code_ranges: list[dict]) -> bytes:
    """Analysis image with exact owner load bytes and explicitly typed EE sections.

    Code may reside after data or in a container's constructor area. This does
    not modify the owner's ELF or change its runtime load/entry contract.
    """
    info=elf_info(original);loads=info['loads']
    result=bytearray(52+32*len(loads));positions=[]
    for segment in loads:
        result.extend(bytes(-len(result)%16));offset=len(result)
        result.extend(original[segment['offset']:segment['offset']+segment['file_size']])
        if len(result)>MAX_PROGRAM:raise PCError('PS2 typed analysis image exceeds its load bound')
        positions.append(offset)
    names=bytearray(b'\0.shstrtab\0');sections=[bytes(40)]
    for n,row in enumerate(code_ranges):
        address,size=row['address'],row['size']
        index=next((i for i in reversed(range(len(loads))) if loads[i]['flags']&1 and
            loads[i]['address']<=address and address+size<=loads[i]['address']+loads[i]['file_size']),None)
        if index is None or not size or address&3 or size&3:
            raise PCError('typed PS2 code must stay in file-backed executable loads')
        name=len(names);names.extend(f'.ee_code_{n}'.encode()+b'\0')
        offset=positions[index]+address-loads[index]['address']
        sections.append(struct.pack('<10I',name,1,6,address,offset,size,0,0,4,0))
    name_offset=len(result);result.extend(names);result.extend(bytes(-len(result)%4))
    sections.append(struct.pack('<10I',1,3,0,0,name_offset,len(names),0,0,1,0))
    section_offset=len(result);result.extend(b''.join(sections))
    struct.pack_into('<16sHHIIIIIHHHHHH',result,0,original[:16],2,8,1,info['entry'],52,section_offset,
        info['flags'],52,32,len(loads),40,len(sections),len(sections)-1)
    for n,segment in enumerate(loads):
        struct.pack_into('<8I',result,52+n*32,1,positions[n],segment['address'],segment['physical_address'],
            segment['file_size'],segment['memory_size'],segment['flags'],1)
    elf_info(result)
    return bytes(result)


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
