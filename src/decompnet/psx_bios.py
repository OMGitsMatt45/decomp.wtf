"""GNU C architectural dispatch to the documented PS1 BIOS vectors.

These hardware thunks intentionally retain the firmware calling convention.
They contain C register assignments and a computed tail jump, never instruction
templates. Ordinary game functions continue using normal C/C++ types and data.
"""

import re
import struct


VECTORS = (0xA0, 0xB0, 0xC0)
_IDENTIFIER = r"[A-Za-z_]\w*"
_INTEGER = r"(?:0[xX][0-9A-Fa-f]{1,8}|0|[1-9][0-9]{0,9})(?:[uU])?"
_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
_DISPATCH = re.compile(
    r'\s*register\s+unsigned\s+int\s+(?P<vector>' + _IDENTIFIER + r')\s+'
    r'(?P<vector_annotation>(?:asm|__asm__)\s*\(\s*"\$10"\s*\))\s*;\s*'
    r'register\s+unsigned\s+int\s+(?P<selector>' + _IDENTIFIER + r')\s+'
    r'(?P<selector_annotation>(?:asm|__asm__)\s*\(\s*"\$9"\s*\))\s*;\s*'
    r'int\s+(?P<name>' + _IDENTIFIER + r')\s*\(\s*\)\s*\{\s*'
    r'(?P=vector)\s*=\s*(?P<vector_value>' + _INTEGER + r')\s*;\s*'
    r'(?P=selector)\s*=\s*(?P<selector_value>' + _INTEGER + r')\s*;\s*'
    r'goto\s*\*\s*\(\s*void\s*\*\s*\)\s*(?P=vector)\s*;\s*\}\s*'
)


def register_annotations(source):
    """Only the two bindings in one complete, literal BIOS tail dispatcher.

    No macros, initializers, extra statements, other computed jumps, symbol
    aliases or instruction strings qualify for the source-check exception.
    """
    def comment(match):
        return re.sub(r"[^\n]", " ", match[0]) if match[0].startswith(("//", "/*")) else match[0]
    match = _DISPATCH.fullmatch(_COMMENTS.sub(comment, source))
    if not match or len({match["vector"], match["selector"], match["name"]}) != 3:
        return []
    number = lambda text: int(text.rstrip("uU"), 16 if text.lower().startswith("0x") else 10)
    if number(match["vector_value"]) not in VECTORS or not 0 <= number(match["selector_value"]) <= 255:
        return []
    return [match.span("vector_annotation"), match.span("selector_annotation")]


def candidates(code, name, context_header=""):
    """A documented hardware C candidate for an exact three-word BIOS stub."""
    if not re.fullmatch(_IDENTIFIER, name) or re.search(r"\b" + re.escape(name) + r"\s*\(", context_header):
        return []
    if len(code) != 12:
        return []
    vector, jump, selector = struct.unpack("<3I", code)
    if vector & 0xFFFF0000 != 0x240A0000 or jump != 0x01400008 or selector & 0xFFFF0000 != 0x24090000:
        return []
    vector, selector = vector & 65535, selector & 65535
    if vector not in VECTORS or selector > 255:
        return []
    return [f'''/* Architectural GNU C BIOS tail dispatch: pinned compiler and PS1 hardware ABI.
 * Firmware consumes the caller's argument registers/stack and returns directly
 * to its return address. The empty C parameter list leaves those ABI inputs
 * unspecified; this wrapper is intentionally not portable C. */
register unsigned int bios_vector asm("$10");
register unsigned int bios_selector asm("$9");
int {name}() {{
    bios_vector = 0x{vector:02X};
    bios_selector = 0x{selector:02X};
    goto *(void *)bios_vector;
}}
''']
