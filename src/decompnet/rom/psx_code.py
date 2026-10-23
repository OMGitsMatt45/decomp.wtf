"""Recover a PS1 text envelope when the initial config excludes the boot entry.

Entry/control-flow evidence and dense ordinary MIPS frame/return clusters seed
the scan. This is analysis evidence, not a runtime loader qualification.
"""

import struct

import rabbitizer


def text_bounds(program):
    load, size = struct.unpack_from("<II", program, 0x18)
    entry = int.from_bytes(program[0x10:0x14], "little")
    words = struct.unpack(f"<{size // 4}I", program[0x800:0x800 + size // 4 * 4])
    seeds = [entry]
    for start in range(0, len(words), 1024):
        block = words[start:start + 1024]
        frames = [start + i for i, word in enumerate(block) if word & 0xFFFF8000 == 0x27BD8000]
        if len(frames) >= 2 and block.count(0x03E00008) >= 2:
            seeds.extend(load + i * 4 for i in frames)
    seen = set()
    while seeds:
        pc = seeds.pop()
        while load <= pc < load + len(words) * 4 and not (pc - load) % 4:
            index = (pc - load) // 4
            if index in seen:
                break
            word = words[index]
            if not rabbitizer.Instruction(word, pc).isValid():
                break
            seen.add(index)
            opcode, function = word >> 26, word & 63
            is_jump = opcode in (2, 3) or (opcode == 0 and function in (8, 9))
            is_branch = opcode in (1, 4, 5, 6, 7)
            if is_jump or is_branch:
                if index + 1 < len(words):
                    seen.add(index + 1)
                if opcode in (2, 3):
                    seeds.append(((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2))
                elif is_branch:
                    offset = word & 0xFFFF
                    seeds.append(pc + 4 + 4 * (offset - 0x10000 if offset & 0x8000 else offset))
                if opcode == 2 or opcode == 0 and function == 8:
                    break
                pc += 8
            else:
                pc += 4
    if not seen:
        return None
    return 0x800 + min(seen) * 4, min(0x800 + size, (0x800 + (max(seen) + 1) * 4 + 15) & ~15)


def repair_config(cfg, program):
    """Keep valid ordinary configs; repair a text guess that misses the boot PC."""
    entry = int.from_bytes(program[0x10:0x14], "little")
    load = int.from_bytes(program[0x18:0x1C], "little")
    entry_offset = 0x800 + entry - load
    segments = cfg["segments"]
    code = next((s for s in segments if isinstance(s, dict) and s.get("type") == "code"), None)
    if not code:
        return False
    subs = code.get("subsegments", [])
    end = next((s[0] for s in segments if isinstance(s, list) and s), len(program))
    if any(s[1] in ("c", "asm") and s[0] <= entry_offset < (subs[i + 1][0] if i + 1 < len(subs) else end)
           for i, s in enumerate(subs) if isinstance(s, list)):
        return False
    bounds = text_bounds(program)
    if not bounds or not bounds[0] <= entry_offset < bounds[1]:
        return False
    start, stop = bounds
    result = [[0x800, "data", "main_prefix"]] if start > 0x800 else []
    result.append([start, "c", "main"])
    if stop < end:
        result.append([stop, "data", "main_suffix"])
    code["subsegments"] = result
    return True
