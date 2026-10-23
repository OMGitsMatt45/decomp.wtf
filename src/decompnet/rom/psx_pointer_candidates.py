"""Bounded alternatives for inferred pointers; the ordinary exact judge decides."""

import re


_SCALAR = r"(?:M2C_UNK(?:8|16|32)?|[su](?:8|16|32))"
_WIDTHS = {"M2C_UNK": 4, "M2C_UNK32": 4, "s32": 4, "u32": 4,
           "M2C_UNK16": 2, "s16": 2, "u16": 2,
           "M2C_UNK8": 1, "s8": 1, "u8": 1,
           "int": 4, "unsigned int": 4, "signed int": 4,
           "short": 2, "unsigned short": 2, "signed short": 2}


def _code(text):
    """Keep token positions while excluding comments and quoted text."""
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda match: re.sub(r"[^\n]", " ", match[0]), text, flags=re.S)


def _closing(text, start):
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if not depth:
                return index
    return None


def _simple_address(expression):
    """An address sum, excluding calls, casts and effects needing type facts."""
    return bool(re.search(r"[+-]", expression)) and not (
        re.search(r"[=,;?:{}\[\].!]|->|\+\+|--|\b[A-Za-z_]\w*\s*\(", expression)
        or re.search(r"\(\s*(?:" + _SCALAR + r"|(?:unsigned|signed|const|void|int|short|char|long)\b)[^()]*\)", expression))


def inferred_pointer_candidates(source, name, context_header=""):
    """Try byte offsets where m2c inferred a word/halfword pointer.

    An unknown automatic ``D_ADDRESS`` object is represented by a scalar. Its
    address arithmetic can retain byte offsets even though C scales offsets by
    that scalar's size. Likewise, inferred ``argN`` pointers can retain byte
    increments. These alternatives change the inferred C only. Reviewed symbols
    and signatures, named user parameters, and explicit pointer casts win.
    """
    code, context = _code(source), _code(context_header)
    if re.search(r"\b" + re.escape(name) + r"\s*\(", context):
        return []
    signature = re.search(r"\b" + re.escape(name) + r"\(([^()]*)\)\s*\{", code)
    if not signature:
        return []
    body_start = signature.end()
    depth, body_end = 1, len(code)
    for index in range(body_start, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if not depth:
                body_end = index
                break
    body = code[body_start:body_end]
    objects = {}
    for declaration in re.finditer(r"(?m)^\s*(?:extern\s+)?(" + _SCALAR + r")\s+(D_[0-9A-Fa-f]{8})\s*;", code[:signature.start()]):
        kind, symbol = declaration.groups()
        if _WIDTHS[kind] > 1 and not re.search(r"\b" + re.escape(symbol) + r"\b", context):
            objects[symbol] = kind
    edits = []
    for match in re.finditer(r"\*\s*\(", body):
        start = body_start + match.start()
        opening = code.index("(", start)
        closing = _closing(code, opening)
        if closing is None or closing >= body_end:
            continue
        expression = code[opening + 1:closing]
        references = re.findall(r"&\s*(D_[0-9A-Fa-f]{8})\b", expression)
        if len(references) != 1 or references[0] not in objects:
            continue
        # Only an opaque object's address plus/minus an integer expression.
        # Existing casts, calls, assignments and pointer/member operations need
        # more type facts, so retain them verbatim.
        if not _simple_address(expression):
            continue
        symbol = references[0]
        original = source[opening + 1:closing]
        address = re.sub(r"&\s*" + re.escape(symbol) + r"\b", "(unsigned int)&" + symbol, original)
        edits.append((start, closing + 1, "*((" + objects[symbol] + " *)(" + address + "))"))
    for statement in re.finditer(r"\breturn\b|(?<![!<>=+\-*/%&|^])=(?!=)", body):
        start = body_start + statement.end()
        stop = code.find(";", start, body_end)
        if stop == -1:
            continue
        expression = code[start:stop]
        # Handle an address value independently from a dereference. Replacing
        # the base of a word load with char* would change its access width.
        if not _simple_address(expression) or re.search(r"\*\s*(?:\(|&)", expression):
            continue
        depth = 0
        for token in expression:
            depth += (token == "(") - (token == ")")
            if depth < 0:
                break
        if depth:
            continue
        references = list(re.finditer(r"&\s*(D_[0-9A-Fa-f]{8})\b", expression))
        if len(references) != 1 or references[0][1] not in objects:
            continue
        reference = references[0]
        edits.append((start + reference.start(), start + reference.end(), "(s8 *)&" + reference[1]))
    for parameter in signature[1].split(","):
        pointer = re.fullmatch(r"\s*(?:const\s+)?(" + _SCALAR + r"|(?:(?:unsigned|signed)\s+)?(?:int|short))\s*\*\s*(arg\d+)\s*", parameter)
        if not pointer:
            continue
        kind, argument = pointer.groups()
        width = _WIDTHS[kind]
        if width == 1:
            continue
        for update in re.finditer(r"\b" + re.escape(argument) + r"\s*[+-]=\s*(0[xX][0-9A-Fa-f]+|\d+)\s*;", body):
            amount = int(update[1], 16 if update[1].lower().startswith("0x") else 10)
            if 0 < amount <= 4096 and amount % width == 0:
                edits.append((body_start + update.start(1), body_start + update.end(1), str(amount // width)))
    # Prefer outer expressions; avoid overlapping replacements and cap work on
    # large drafts. Each individual edit and the combined alternative is tried.
    chosen, end = [], -1
    for edit in sorted(edits):
        if edit[0] >= end:
            chosen.append(edit)
            end = edit[1]
        if len(chosen) == 12:
            break
    if not chosen:
        return []

    def apply(changes):
        result = source
        for start, end, replacement in reversed(changes):
            result = result[:start] + replacement + result[end:]
        return result

    return list(dict.fromkeys([apply(chosen)] + [apply([edit]) for edit in chosen]))
