"""Recover callbacks from the Thumb linker loop for relative constructors."""
from __future__ import annotations

import struct


def entries(code: bytes, segments: list[dict]) -> set[int]:
    text, *data_segments = segments
    base = text['address']
    raw = code[:text['size']]
    # ldr r4, [pc, #24]; add r4, pc; ldr r5, [pc, #24]; add r5, pc;
    # b compare; ldr r0, [r4]; adds r0, r0, r4; blx r0; adds r4, #4;
    # compare: cmp r4, r5; blt loop; pop {r4, r5, r6, pc}.
    loop = struct.pack('<12H', 0x4c06, 0x447c, 0x4d06, 0x447d, 0xe003, 0x6820,
                       0x1900, 0x4780, 0x1d24, 0x42ac, 0xd1f9, 0xbd70)
    callbacks = set()
    start = 0
    while (offset := raw.find(loop, start)) >= 0:
        start = offset + len(loop)
        if offset % 4 != 2 or offset < 2 or raw[offset - 2:offset] != b'\x70\xb5':
            continue
        literal = ((offset + 4) & ~3) + 24
        if literal + 8 > len(raw):
            continue
        lo, hi = struct.unpack_from('<II', raw, literal)
        begin = (base + offset + 6 + lo) & 0xffffffff
        end = (base + offset + 10 + hi) & 0xffffffff
        if begin % 4 or end % 4 or not 0 < end - begin <= 4096 * 4:
            continue
        for segment in data_segments:
            addr = segment['address']
            if not addr <= begin < end <= addr + segment['size']:
                continue
            index = segment['code_offset'] + begin - addr
            table = code[index:index + end - begin]
            targets = [(begin + i * 4 + delta) & 0xffffffff
                       for i, (delta,) in enumerate(struct.iter_unpack('<I', table))]
            if all(base <= (target & ~1) < base + len(raw)
                   and (target & 1 or target % 4 == 0) for target in targets):
                callbacks.update(targets)
            break
    return callbacks
