"""C++ game sources with the original C game's external symbol names."""

import re

_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
_DIRECTIVES = re.compile(r"^[ \t]*\#(?:[^\n\\]|\\[^\n]|\\\n)*", re.M)
_GP_REGISTER = re.compile(r'\s*register\s+unsigned\s+int\s+[A-Za-z_]\w*\s+'
                          r'(?P<annotation>(?:asm|__asm__)\s*\(\s*"\$28"\s*\))\s*;\s*')


def gp_register_annotations(source: str) -> list[tuple[int, int]]:
    """Exact top-level GCC GP register bindings, with no instruction template.

    This recognizes a declaration of an architectural register, rather than an
    assembly statement or symbol-name annotation. Strings, macros, initializers,
    other registers and declarations inside function bodies do not qualify.
    """
    blank = lambda match: re.sub(r"[^\n]", " ", match[0])
    # Keep the literal register name for validation; ignore punctuation inside
    # comments, strings and directives when locating complete declarations.
    declarations = _DIRECTIVES.sub(blank, _COMMENTS.sub(
        lambda match: blank(match) if match[0].startswith(("//", "/*")) else match[0], source))
    clean = _DIRECTIVES.sub(blank, _COMMENTS.sub(blank, source))
    depth, start, annotations = 0, 0, []
    for token in re.finditer(r"[{};]", clean):
        char = token[0]
        if depth == 0 and char == ";":
            match = _GP_REGISTER.fullmatch(declarations[start:token.end()])
            if match:
                annotations.append((start + match.start("annotation"), start + match.end("annotation")))
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                start = token.end()
        elif depth == 0:
            start = token.end()
    return annotations


def language(config: dict) -> str:
    compiler = config.get("compiler", {})
    platform, toolchain = config.get("platform", "n64"), compiler.get("toolchain")
    if config.get("rom", {}).get("boot_utility") and compiler.get("language") == "asm" \
            and compiler.get("assembly_dialect") == "gnu" \
            and ((platform == "nds" and toolchain == "binutils-arm")
                 or (platform in ("gc", "wii") and toolchain == "gc-wii-binutils")):
        return "asm"
    if platform in ("gb", "gbc") or compiler.get("language") == "asm":
        if platform not in ("gb", "gbc") or toolchain != "rgbds" or compiler.get("language", "asm") != "asm":
            raise ValueError("GB/GBC assembly projects require RGBDS and compiler.language = 'asm'")
        return "asm"
    supported = (platform == "n64" and toolchain in ("gcc-2.7.2-kmc", "ido-7.1", "ido-5.3")) \
        or (platform == "gba" and toolchain == "agbcc") \
        or (platform == "psx" and toolchain in ("gcc-2.7.2-psx", "gcc-2.8.1-psx")) \
        or (platform == "ps2" and toolchain == "ee-gcc-2.96")
    default = "c++" if config.get("kind") == "rom" and supported else "c"
    value = compiler.get("language", default)
    if value not in ("c", "c++"):
        raise ValueError("compiler.language must be 'c' or 'c++'")
    return value


def ido_frontend(config: dict) -> str | None:
    compiler = config.get("compiler", {})
    if language(config) == "c++" and compiler.get("toolchain") in ("ido-5.3", "ido-7.1"):
        return compiler.get("cpp_frontend", "edg")
    return None


def game_abi(source: str) -> str:
    """Give plain global definitions/externs C linkage; leave C++ helpers intact.

    Namespaces, classes, templates, static functions and explicit linkage blocks
    retain their authored linkage. No function bodies or types are rewritten.
    This is shared by the judge and exported sources, which are real C++ units.
    """
    blank = lambda match: re.sub(r"[^\n]", " ", match[0])
    clean = _DIRECTIVES.sub(blank, _COMMENTS.sub(blank, source))
    register_annotations = gp_register_annotations(source)
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
                cpp_operator = re.search(r"\boperator\b", code)
                if not explicit and not cpp_operator and re.match(r"extern\b", code):
                    edits.append((pos + len("extern"), ' "C"'))
                elif not explicit and not cpp_operator and code.rstrip().endswith(")") and "=" not in code \
                        and not any(pos <= begin < at for begin, _ in register_annotations) \
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
