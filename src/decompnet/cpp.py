"""C++ game sources with the original C game's external symbol names."""

import re

_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
_DIRECTIVES = re.compile(r"^[ \t]*\#(?:[^\n\\]|\\[^\n]|\\\n)*", re.M)


def language(config: dict) -> str:
    compiler = config.get("compiler", {})
    default = "c++" if config.get("kind") == "rom" and config.get("platform", "n64") == "n64" \
        and compiler.get("toolchain") in ("gcc-2.7.2-kmc", "ido-7.1") else "c"
    value = compiler.get("language", default)
    if value not in ("c", "c++"):
        raise ValueError("compiler.language must be 'c' or 'c++'")
    return value


def game_abi(source: str) -> str:
    """Give plain global definitions/externs C linkage; leave C++ helpers intact.

    Namespaces, classes, templates, static functions and explicit linkage blocks
    retain their authored linkage. No function bodies or types are rewritten.
    This is shared by the judge and exported sources, which are real C++ units.
    """
    blank = lambda match: re.sub(r"[^\n]", " ", match[0])
    clean = _DIRECTIVES.sub(blank, _COMMENTS.sub(blank, source))
    depth, start, edits = 0, 0, []
    for token in re.finditer(r"[{};]", clean):
        char, at = token[0], token.start()
        if depth == 0 and char in ("{", ";"):
            declaration = clean[start:at]
            first = re.search(r"\S", declaration)
            if first:
                pos = start + first.start()
                text = source[pos:at]
                code = clean[pos:at]
                explicit = re.search(r'\bextern\s*"C(?:\+\+)?"', text)
                if not explicit and re.match(r"extern\b", code):
                    edits.append((pos + len("extern"), ' "C"'))
                elif not explicit and code.rstrip().endswith(")") and "=" not in code \
                        and not re.search(r"\b(template|namespace|static|typedef|using)\b|::", code) \
                        and re.search(r"\b\w+\s*\((?!\s*\*)", code):
                    edits.append((pos, 'extern "C" '))
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                start = token.end()
        elif depth == 0:
            start = token.end()
    for pos, value in reversed(edits):
        source = source[:pos] + value + source[pos:]
    return source
