"""Conservative word-argument hints for another m2c candidate, never match facts.

m2c can omit an untouched argument register at a call and shift the remaining
arguments left. Callee entry reads plus explicit caller writes expose some of
those holes. Supplying a full prototype lets m2c reconstruct the expressions;
the ordinary compiler/full-link judge still decides whether the source matches.
"""

import re
import struct
from collections import defaultdict


def _effects(word):
    """(read GPR mask, written GPR mask, control transfer), or unknown."""
    op, rs, rt, rd, function = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word & 63
    bit = lambda reg: 1 << reg if reg else 0
    if op == 0:
        if function in (0, 2, 3):
            return bit(rt), bit(rd), False
        if function in (4, 6, 7, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43):
            return bit(rs) | bit(rt), bit(rd), False
        if function in (8, 9):
            return bit(rs), bit(rd) if function == 9 else 0, True
        if function in (16, 18):
            return 0, bit(rd), False
        if function in (17, 19):
            return bit(rs), 0, False
        if function in (24, 25, 26, 27):
            return bit(rs) | bit(rt), 0, False
    elif op == 1 and rt in (0, 1):
        return bit(rs), 0, True
    elif op in (2, 3):
        return 0, bit(31) if op == 3 else 0, True
    elif op in (4, 5):
        return bit(rs) | bit(rt), 0, True
    elif op in (6, 7):
        return bit(rs), 0, True
    elif 8 <= op <= 14:
        return bit(rs), bit(rt), False
    elif op == 15:
        return 0, bit(rt), False
    elif op in (32, 33, 34, 35, 36, 37, 38):
        return bit(rs) | (bit(rt) if op in (34, 38) else 0), bit(rt), False
    elif op in (40, 41, 42, 43, 46):
        return bit(rs) | bit(rt), 0, False
    # Float/wide, coprocessor, syscall and unknown instructions need ABI facts.
    return None


def _words(code):
    return struct.unpack(f"<{len(code) // 4}I", code) if code and len(code) % 4 == 0 else ()


def entry_arguments(code):
    """Incoming a0..a3 read before overwrite in a straight-line entry prefix.

    Stop after the first control transfer's delay slot. This proves only a
    lower bound; arguments used exclusively on later paths are not inferred.
    """
    written, incoming, remaining = 0, 0, None
    for word in _words(code):
        effect = _effects(word)
        if effect is None:
            return None
        reads, writes, control = effect
        if remaining is not None and control:
            return None
        incoming |= reads & ~written
        written |= writes
        if remaining == 0:
            break
        if control:
            remaining = 0
    return incoming >> 4 & 15


def call_sites(code, vram):
    """Direct JAL addresses and a0..a3 writes in their final basic blocks."""
    words, written, sites, index = _words(code), 0, defaultdict(list), 0
    while index < len(words):
        word = words[index]
        effect = _effects(word)
        if effect is None:
            return {}
        _, writes, control = effect
        written |= writes
        if control:
            if index + 1 >= len(words):
                return {}
            delay = _effects(words[index + 1])
            if delay is None or delay[2]:
                return {}
            written |= delay[1]
            if word >> 26 == 3:
                address = (vram + index * 4 + 4) & 0xF0000000 | (word & 0x3FFFFFF) << 2
                sites[address].append(written >> 4 & 15)
            written = 0
            index += 2
        else:
            index += 1
    return dict(sites)


_TYPES = {"M2C_UNK": "int", "M2C_UNK8": "signed char", "M2C_UNK16": "short", "M2C_UNK32": "int",
          "s8": "signed char", "u8": "unsigned char", "s16": "short", "u16": "unsigned short",
          "s32": "int", "u32": "unsigned int", "s32_bool": "int"}
_WORD = re.compile(r"(?:(?:signed|unsigned)\s+)?(?:char|short(?: int)?|int|long(?: int)?)|unsigned|signed")


def _word_type(text, *, returns=False):
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"\s+arg\d+$", "", text)
    if text in _TYPES:
        return _TYPES[text]
    if _WORD.fullmatch(text) or returns and text == "void":
        return text
    if "*" in text and re.fullmatch(r"[A-Za-z_][\w\s]*(?:\s*\*\s*(?:const|volatile)?\s*)+", text):
        # Pointers occupy one o32 word; function pointers and references are not
        # described by this simple inferred-prototype syntax.
        base = text.split("*", 1)[0].strip()
        if base == "void" or base in _TYPES or _WORD.fullmatch(base):
            return _TYPES.get(base, base) + " " + text[len(base):].strip()
    return None


def call_context(net, proj, fn, draft, context_header):
    """Extra temporary declarations for inferred direct calls, or an empty string.

    Reviewed prototypes win. Only simple one-word return/parameter types and
    unambiguous same-project callees qualify. Conflicting call-site layouts,
    missing callee facts and wide/float/unknown ABIs leave the draft unchanged.
    """
    if net.cfg(proj).get("platform") != "psx":
        return ""
    sites, hints = call_sites(fn["target"], fn["vram"]), []
    if not sites:
        return ""
    rows = net.store.all("SELECT id,vram,unit,target FROM functions WHERE project_id=? ORDER BY id", proj["id"])
    fingerprint = tuple((row["id"], row["vram"], row["unit"], hash(row["target"])) for row in rows)
    cache = getattr(net, "_psx_abi_summaries", None)
    if cache is None:
        cache = net._psx_abi_summaries = {}
    previous = cache.get(proj["id"])
    if previous is None or previous[0] != fingerprint:
        from .psx_abi import argument_summaries
        previous = (fingerprint, argument_summaries(rows))
        cache[proj["id"]] = previous
    summaries = previous[1]
    symbols = net.symbols(proj["id"])
    for prototype in re.finditer(r"(?m)^([^\n;{}]+?)\b([A-Za-z_]\w*)\(([^()]*)\)\s*;", draft):
        result, name, raw = prototype.groups()
        if re.search(r"\b" + re.escape(name) + r"\s*\(", context_header):
            continue
        result = _word_type(result, returns=True)
        parameters = [] if raw.strip() in ("", "void") else [_word_type(p) for p in raw.split(",")]
        address = symbols.resolve(name)
        masks = sites.get(address, [])
        if result is None or any(p is None for p in parameters) or len(parameters) > 4 or not masks or len(set(masks)) != 1:
            continue
        callees = net.store.all("SELECT * FROM functions WHERE project_id=? AND vram=?", proj["id"], address)
        own = [callee for callee in callees if callee["unit"] == fn["unit"]]
        callee = own[0] if len(own) == 1 else callees[0] if len(callees) == 1 else None
        if callee is None:
            continue
        from .psx_abi import argument_packet
        if argument_packet(callee["target"]):
            continue
        incoming = summaries.get((callee["vram"], callee["unit"]), entry_arguments(callee["target"]))
        writes = masks[0]
        if incoming is None:
            continue
        slots = (incoming | writes).bit_length()
        if slots <= len(parameters):
            continue
        # An inferred m2c parameter must correspond to an explicitly prepared
        # argument word; otherwise its original position is not established.
        if len(parameters) != writes.bit_count():
            continue
        types = iter(parameters)
        repaired = [next(types) if writes >> slot & 1 else "int" for slot in range(slots)]
        hints.append(f"{result} {name}({', '.join(repaired)});")
    return "\n".join(hints)
