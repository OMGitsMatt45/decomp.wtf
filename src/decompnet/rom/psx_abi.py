"""Bounded MIPS I register-use summaries for another C/C++ draft candidate.

An argument mask describes a0..a3 reads reachable before their first overwrite.
It is a lower bound on the incoming word registers a function may need, not a
reviewed C signature. Known callees contribute their own proven reads; unknown
external calls contribute none. The ordinary complete-link judge remains final.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from bisect import bisect_right
import struct


_AMBIGUOUS = object()


@dataclass(frozen=True, slots=True)
class _Instruction:
    reads: int
    writes: int
    transfer: str = ""
    target: int | None = None


@dataclass(frozen=True, slots=True)
class _Node:
    reads: int
    writes: int
    successors: tuple
    callee: object = None
    call: bool = False


def _instruction(word, address):
    """Only ordinary integer MIPS I instructions have established effects here."""
    op, rs, rt, rd = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31
    shift, function = word >> 6 & 31, word & 63
    bit = lambda reg: 1 << (reg - 4) if 4 <= reg <= 7 else 0
    immediate = word & 65535
    signed = immediate - (65536 if immediate & 32768 else 0)
    branch = address + 4 + signed * 4
    if op == 0:
        if function in (0, 2, 3) and rs == 0:
            return _Instruction(bit(rt), bit(rd))
        if function in (4, 6, 7, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43) and shift == 0:
            return _Instruction(bit(rs) | bit(rt), bit(rd))
        if function == 8 and rt == rd == shift == 0:
            return _Instruction(0, 0, "return" if rs == 31 else "dynamic")
        if function == 9 and rt == shift == 0:
            return _Instruction(bit(rs), bit(rd), "dynamic")
        if function in (16, 18) and rs == rt == shift == 0:
            return _Instruction(0, bit(rd))
        if function in (17, 19) and rt == rd == shift == 0:
            return _Instruction(bit(rs), 0)
        if function in (24, 25, 26, 27) and rd == shift == 0:
            return _Instruction(bit(rs) | bit(rt), 0)
    elif op in (2, 3):
        target = (address + 4) & 0xF0000000 | (word & 0x3FFFFFF) << 2
        return _Instruction(0, 0, "call" if op == 3 else "jump", target)
    elif op in (4, 5):
        transfer = "branch"
        if rs == rt:
            transfer = "taken" if op == 4 else "untaken"
        return _Instruction(bit(rs) | bit(rt), 0, transfer, branch)
    elif op in (6, 7) and rt == 0:
        transfer = "branch" if rs else "taken" if op == 6 else "untaken"
        return _Instruction(bit(rs), 0, transfer, branch)
    elif op == 1 and rt in (0, 1):
        transfer = "branch" if rs else "taken" if rt == 1 else "untaken"
        return _Instruction(bit(rs), 0, transfer, branch)
    elif 8 <= op <= 14:
        return _Instruction(bit(rs), bit(rt))
    elif op == 15 and rs == 0:
        return _Instruction(0, bit(rt))
    elif op in (32, 33, 35, 36, 37):
        return _Instruction(bit(rs), bit(rt))
    elif op in (34, 38):
        # LWL/LWR merge with the old register value.
        return _Instruction(bit(rs) | bit(rt), bit(rt))
    elif op in (40, 41, 42, 43, 46):
        return _Instruction(bit(rs) | bit(rt), 0)
    return None


def argument_packet(code):
    """Whether the entry saves a3 in its incoming o32 argument home slot.

    Variadic functions save optional register words regardless of how many C
    arguments a particular call supplies. Follow simple SP-relative aliases to
    recognize that packet, including stores through a va_list pointer. A fixed
    four-argument function may use the same prologue; its mandatory arity also
    needs reviewed facts rather than this register-save pattern.
    """
    if not isinstance(code, (bytes, bytearray, memoryview)) or len(code) % 4:
        return False
    aliases, delay = {29: 0}, False
    for index, (word,) in enumerate(struct.iter_unpack("<I", code)):
        if index >= 64:
            break
        effect = _instruction(word, index * 4)
        if effect is None or delay and effect.transfer:
            return False
        op, rs, rt, rd, function = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word & 63
        signed = (word & 65535) - (65536 if word & 32768 else 0)
        if op == 43 and rt == 7 and rs in aliases and aliases[rs] + signed == 12:
            return True
        destination, value = None, None
        if op in (8, 9) and rs in aliases:
            destination, value = rt, aliases[rs] + signed
        elif op == 0 and function in (33, 37) and (rs == 0 or rt == 0):
            destination, value = rd, aliases.get(rt if rs == 0 else rs)
        elif op == 0 and function in (0, 2, 3, 4, 6, 7, 16, 18, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43):
            destination = rd
        elif 8 <= op <= 15 or op in (32, 33, 34, 35, 36, 37, 38):
            destination = rt
        if destination:
            if value is None:
                aliases.pop(destination, None)
            else:
                aliases[destination] = value
        if delay:
            break
        delay = bool(effect.transfer)
    return False


def _graph(code, vram, resolve, max_words):
    if not isinstance(vram, int) or isinstance(vram, bool) or not 0 <= vram <= 0xFFFFFFFF or vram % 4:
        return None
    if not isinstance(code, (bytes, bytearray, memoryview)) or not code or len(code) % 4 \
            or len(code) > max_words * 4 or vram + len(code) > 0x100000000:
        return None
    if argument_packet(code):
        return None
    words = struct.unpack(f"<{len(code) // 4}I", code)
    nodes, delays, pending = {}, set(), [0]
    while pending:
        index = pending.pop()
        if index in delays or not 0 <= index < len(words):
            return None
        if index in nodes:
            continue
        current = _instruction(words[index], vram + index * 4)
        if current is None or current.transfer == "dynamic":
            return None
        reads, writes, callee, call = current.reads, current.writes, None, False
        if current.transfer:
            if index + 1 >= len(words) or index + 1 in nodes:
                return None
            delay = _instruction(words[index + 1], vram + (index + 1) * 4)
            if delay is None or delay.transfer:
                return None
            delays.add(index + 1)
            reads |= delay.reads & ~writes
            writes |= delay.writes
            if current.transfer == "return":
                successors = ()
            elif current.transfer == "call":
                callee = resolve(current.target)
                if callee is _AMBIGUOUS:
                    return None
                call, successors = True, (index + 2,)
            else:
                target = (current.target - vram) // 4
                if current.transfer in ("jump", "taken"):
                    successors = (target,)
                elif current.transfer == "untaken":
                    successors = (index + 2,)
                else:
                    successors = tuple(dict.fromkeys((target, index + 2)))
        else:
            successors = (index + 1,)
        # Falling or branching outside the registered function needs reviewed
        # tail/secondary-entry facts, even if another function starts there.
        if any(not 0 <= successor < len(words) for successor in successors):
            return None
        nodes[index] = _Node(reads, writes, successors, callee, call)
        pending.extend(successors)
    return nodes


class _Limit(Exception):
    pass


def _evaluate(graph, masks, budget):
    live, pending, queued, result = {0: 15}, deque([0]), {0}, 0
    while pending:
        budget[0] -= 1
        if budget[0] < 0:
            raise _Limit()
        index = pending.popleft()
        queued.remove(index)
        node, incoming = graph[index], live[index]
        reads = node.reads
        if node.call:
            # The delay slot executes before the callee consumes its arguments.
            reads |= masks.get(node.callee, 0) & ~node.writes
        result |= incoming & reads
        outgoing = 0 if node.call else incoming & ~node.writes
        if not outgoing:
            continue
        for successor in node.successors:
            previous = live.get(successor, 0)
            combined = previous | outgoing
            if combined != previous:
                live[successor] = combined
                if successor not in queued:
                    pending.append(successor)
                    queued.add(successor)
    return result


def incoming_arguments(code, vram, callees=None, *, max_words=16384, max_steps=1000000):
    """Summarize one function, with optional direct callee address -> mask facts.

    Unknown direct callees add no argument facts. A None callee mask marks an
    ambiguous target and rejects the summary. A missing/unsupported result is
    None, distinct from a proven empty read mask (zero).
    """
    callees = callees or {}
    if any(mask is not None and (not isinstance(mask, int) or isinstance(mask, bool) or not 0 <= mask <= 15)
           for mask in callees.values()):
        return None
    def resolve(address):
        if address in callees:
            return _AMBIGUOUS if callees[address] is None else address
        if vram < address < vram + len(code):
            return _AMBIGUOUS
        return None
    graph = _graph(code, vram, resolve, max_words)
    if graph is None:
        return None
    try:
        return _evaluate(graph, {key: value for key, value in callees.items() if value is not None}, [max_steps])
    except _Limit:
        return None


def argument_summaries(functions, *, max_words=16384, max_total_words=1000000,
                       max_steps=8000000, max_functions=16384):
    """Return {(vram, unit): incoming a0..a3 mask} at a bounded fixed point.

    Rows provide ``vram``, ``unit`` and original ``target`` bytes. Overlapping
    overlays resolve to their own unit first. Ambiguous entries, indirect/tail
    transfers, malformed reachable instructions and unsupported ISA are omitted.
    Exhausting a project-wide bound returns no inferred facts.
    """
    rows, duplicates, by_address, intervals, total = {}, set(), defaultdict(set), defaultdict(list), 0
    for count, row in enumerate(functions, 1):
        if count > max_functions:
            return {}
        address, unit, code = row["vram"], row["unit"], row["target"]
        if not isinstance(address, int) or isinstance(address, bool) or not isinstance(unit, str) \
                or not isinstance(code, (bytes, bytearray, memoryview)):
            continue
        total += (len(code) + 3) // 4
        if total > max_total_words:
            return {}
        key = (address, unit)
        if key in rows:
            duplicates.add(key)
        rows[key] = code
        by_address[address].add(key)
        intervals[unit].append((address, address + len(code)))
    # Prefix maximum ends detect interior targets even in overlapping ranges.
    ranges = {}
    for unit, values in [*intervals.items(), (None, [value for group in intervals.values() for value in group])]:
        starts, ends, maximum = [], [], -1
        for start, end in sorted(values):
            starts.append(start)
            maximum = max(maximum, end)
            ends.append(maximum)
        ranges[unit] = (starts, ends)
    def interior(address, unit):
        starts, ends = ranges.get(unit, ((), ()))
        index = bisect_right(starts, address) - 1
        return index >= 0 and address < ends[index]
    graphs, callers = {}, defaultdict(set)
    for key, code in rows.items():
        if key in duplicates:
            continue
        def resolve(address):
            own = (address, key[1])
            if own in rows:
                return _AMBIGUOUS if own in duplicates else own
            candidates = by_address.get(address, ())
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                return _AMBIGUOUS if candidate in duplicates else candidate
            if candidates or interior(address, key[1]) or interior(address, None):
                return _AMBIGUOUS
            return None
        graph = _graph(code, key[0], resolve, max_words)
        if graph is not None:
            graphs[key] = graph
            for node in graph.values():
                if node.call and node.callee is not None:
                    callers[node.callee].add(key)
    masks = {key: 0 for key in graphs}
    pending, queued, budget = deque(graphs), set(graphs), [max_steps]
    try:
        while pending:
            key = pending.popleft()
            queued.remove(key)
            mask = _evaluate(graphs[key], masks, budget)
            if mask != masks[key]:
                masks[key] = mask
                for caller in callers[key]:
                    if caller not in queued:
                        pending.append(caller)
                        queued.add(caller)
    except _Limit:
        return {}
    return masks
