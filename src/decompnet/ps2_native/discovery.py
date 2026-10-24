"""Bounded R5900 control-flow discovery from owner ELF bytes.

This records reachable instructions and direct-call seeds, not a complete
function map. Indirect calls/jump tables and system services stay explicit.
Valid-looking words after a return are not automatically promoted to EE code.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
import hashlib
import struct

import rabbitizer

from ..pc import PCError
from .media import MAX_PROGRAM, elf_info


def discover(original: bytes, *, roots=(), max_instructions: int = 2_000_000) -> dict:
    if len(original) > MAX_PROGRAM: raise PCError('PS2 discovery program exceeds its 32 MiB input bound')
    info = elf_info(original)
    if info['symbols'] > MAX_PROGRAM // 16: raise PCError('PS2 discovery symbol inventory exceeds its bound')
    if not 0 < max_instructions <= 8_388_608: raise PCError('PS2 discovery instruction bound is invalid')
    sections = sorted(info['executable_sections'], key=lambda s: s['address'])
    source = 'executable-sections'
    if not sections:
        source = 'executable-load-segments'
        sections = [dict(address=s['address'], size=s['file_size'], offset=s['offset'])
            for s in info['loads'] if s['flags'] & 1 and s['file_size']]
        sections.sort(key=lambda s: s['address'])
    for section in sections:
        if not any(s['address'] <= section['address'] and
                   section['address'] - s['address'] + section['size'] <= s['file_size'] and
                   section['offset'] == s['offset'] + section['address'] - s['address']
                   for s in info['loads']):
            raise PCError('PS2 discovery executable section differs from its load mapping')
    for left, right in zip(sections, sections[1:]):
        if left['address'] + left['size'] > right['address']:
            raise PCError('PS2 discovery needs non-overlapping executable mappings')
    starts = [s['address'] for s in sections]

    def offset(pc):
        n = bisect_right(starts, pc) - 1
        if n < 0 or pc & 3: return None
        section = sections[n]
        if pc + 4 > section['address'] + section['size']: return None
        return section['offset'] + pc - section['address']

    seeds = {}
    def seed(pc, reason):
        if not isinstance(pc, int) or offset(pc) is None:
            raise PCError('PS2 discovery root is outside file-backed executable bytes')
        if pc not in seeds and len(seeds) >= 100_000: raise PCError('PS2 discovery has too many roots')
        seeds.setdefault(pc, set()).add(reason)
    seed(info['entry'], 'elf-entry')
    section_offset = struct.unpack_from('<I', original, 32)[0]
    section_count = struct.unpack_from('<H', original, 48)[0]
    # Names and string tables are not needed for numeric STT_FUNC roots. Read
    # only tables already bounded by elf_info, including repeated table counts.
    for index in range(section_count):
        fields = struct.unpack_from('<10I', original, section_offset + index * 40)
        if fields[1] not in (2, 11): continue
        for position in range(fields[4], fields[4] + fields[5], 16):
            _, address, _, kind, _, section_index = struct.unpack_from('<IIIBBH', original, position)
            if kind & 15 == 2 and section_index not in (0, 0xFFF1): seed(address, 'elf-symbol')
    for pc in roots: seed(pc, 'supplied-root')

    pending = deque(seeds)
    processed, reached = set(), {}
    calls, unresolved, invalid, services = [], [], [], []
    def follow(pc, target, kind):
        if offset(target) is None:
            unresolved.append(dict(pc=pc, target=target, kind=kind + '-outside-executable'))
        else: pending.append(target)
    def decode(pc):
        position = offset(pc)
        if position is None: return None
        return rabbitizer.Instruction(struct.unpack_from('<I', original, position)[0], pc,
            category=rabbitizer.InstrCategory.R5900)
    while pending:
        pc = pending.pop()
        if pc in processed: continue
        processed.add(pc)
        if len(processed) > max_instructions:
            raise PCError('PS2 discovery exceeds its instruction bound; no complete map was produced')
        instruction = decode(pc)
        if instruction is None:
            unresolved.append(dict(pc=pc, kind='target-outside-executable')); continue
        if not instruction.isValid():
            invalid.append(dict(pc=pc, word=instruction.getRaw(), kind='invalid-instruction')); continue
        reached[pc] = instruction.getRaw()
        word = instruction.getRaw()
        op, rs, rt, rd = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        is_call = instruction.isFunctionCall() and not (op == 0 and (word & 63) == 9 and rd == 0)
        taken = True if instruction.isUnconditionalBranch() else None
        if op in (4, 5, 20, 21) and rs == rt: taken = op in (4, 20)
        elif op in (6, 7, 22, 23) and rs == 0: taken = op in (6, 22)
        elif op == 1 and rs == 0 and rt in (0, 1, 2, 3, 16, 17, 18, 19): taken = bool(rt & 1)
        if instruction.hasDelaySlot() and not (instruction.isBranchLikely() and taken is False):
            delay = decode(pc + 4)
            if delay is None or not delay.isValid() or delay.hasDelaySlot():
                invalid.append(dict(pc=pc + 4, kind='invalid-or-control-flow-delay-slot')); continue
            reached[pc + 4] = delay.getRaw()
            if len(reached) > max_instructions:
                raise PCError('PS2 discovery exceeds its instruction bound; no complete map was produced')
        if instruction.isJumpWithAddress() or instruction.isBranch():
            target = (instruction.getInstrIndexAsVram() if instruction.isJumpWithAddress()
                      else instruction.getBranchVramGeneric())
            if taken is not False: follow(pc, target, 'target')
            if is_call and taken is not False:
                calls.append(dict(pc=pc, target=target))
                if offset(target) is not None: seed(target, 'direct-call')
            # A linked unconditional branch also returns to PC+8.
            if is_call or instruction.isBranch() and taken is not True:
                follow(pc, pc + 8, 'continuation')
        elif instruction.isJump():
            is_return = instruction.isReturn() or (op == 0 and (word & 63) == 9 and rd == 0 and rs == 31)
            if not is_return:
                unresolved.append(dict(pc=pc, kind='indirect-call' if is_call
                    else 'indirect-jump', register=(instruction.getRaw() >> 21) & 31))
            if is_call: follow(pc, pc + 8, 'continuation')
        elif instruction.getOpcodeName() in ('eret', 'break'):
            services.append(dict(pc=pc, kind=instruction.getOpcodeName()))
        else:
            if instruction.getOpcodeName() == 'syscall': services.append(dict(pc=pc, kind='syscall'))
            follow(pc, pc + 4, 'fallthrough')
    ranges = []
    for pc in sorted(reached):
        if (ranges and pc == ranges[-1]['address'] + ranges[-1]['size'] and
                offset(pc) == offset(ranges[-1]['address']) + ranges[-1]['size']): ranges[-1]['size'] += 4
        else: ranges.append(dict(address=pc, size=4))
    for span in ranges:
        position = offset(span['address'])
        span['sha256'] = hashlib.sha256(original[position:position + span['size']]).hexdigest()
    return dict(schema='decomp.wtf.ps2-code-discovery/v1', original_elf_sha256=info['sha256'],
        mapping_source=source, coverage='reachable-from-declared-roots', complete_function_map=False,
        native_game_qualified=False, instructions=len(reached), code_ranges=ranges,
        function_seeds=[dict(address=pc, reasons=sorted(reasons)) for pc, reasons in sorted(seeds.items())],
        direct_calls=sorted(calls, key=lambda c: c['pc']),
        unresolved=sorted(unresolved, key=lambda c: c['pc']),
        invalid=sorted(invalid, key=lambda c: c['pc']), services=sorted(services, key=lambda c: c['pc']))
