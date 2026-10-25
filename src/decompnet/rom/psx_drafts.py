"""Restore reviewed PS1 GP facts for source inference, without changing targets."""

import re


def global_pointer_asm(assembly: str, gp: int) -> tuple[str, set[str]]:
    """Name literal GP references for m2c when this module's entry GP is known.

    Reconstruction deliberately keeps these operands numeric. Inference needs
    their addresses instead. A function that changes GP needs additional flow
    facts, so leave that entire listing alone.
    """
    if not isinstance(gp, int) or isinstance(gp, bool) or not 0 < gp <= 0xFFFFFFFF:
        return assembly, set()
    lines = [re.sub(r"/\*.*?\*/", "", line).strip() for line in assembly.splitlines()]
    for line in lines:
        destination = re.match(r"(\w+)\s+\$gp\s*(?:,|$)", line)
        if destination and destination[1] not in ("sb", "sh", "sw", "swl", "swr"):
            return assembly, set()
    symbols = set()

    def address(text):
        offset = int(text, 16 if "0x" in text.lower() else 10)
        if 0x8000 <= offset <= 0xFFFF:
            offset -= 0x10000
        if not -0x8000 <= offset <= 0x7FFF:
            return None
        symbol = f"D_{(gp + offset) & 0xFFFFFFFF:08X}"
        symbols.add(symbol)
        return f"%gp_rel({symbol})"

    def memory(match):
        expression = address(match[1])
        return expression + "($gp)" if expression else match[0]

    def pointer(match):
        expression = address(match[2])
        return match[1] + expression if expression else match[0]

    assembly = re.sub(r"(?<![\w])(-?0[xX][0-9A-Fa-f]+|-?\d+)\(\$gp\)", memory, assembly)
    assembly = re.sub(r"(\baddiu\s+\$\w+\s*,\s*\$gp\s*,\s*)(-?0[xX][0-9A-Fa-f]+|-?\d+)\b", pointer, assembly)
    return assembly, symbols


def global_pointer_source(source: str, symbols: set[str], context: str) -> str:
    """Generated small-global declarations must keep the compiler's GP access.

    The period compilers use tentative common declarations for small data.
    Explicitly reviewed context declarations take precedence over inference.
    """
    for symbol in symbols:
        if re.search(r"\b" + re.escape(symbol) + r"\b", context):
            continue
        source = re.sub(r"(?m)^extern ([^;\n{}]*\b" + re.escape(symbol) + r"\b[^;\n{}]*;)",
                        r"\1", source)
    return source
