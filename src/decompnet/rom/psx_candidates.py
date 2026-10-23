"""Alternative inferred o32 signatures, requiring the ordinary exact judge."""

import re


def recovery_candidates(source, name, context_header=""):
    """Keep the original draft and bounded inferred type/address alternatives."""
    from .psx_pointer_candidates import inferred_pointer_candidates
    pointers = inferred_pointer_candidates(source, name, context_header)
    variants = [source, *pointers, *inferred_parameter_candidates(source, name, context_header)]
    for pointer in pointers[:3]:
        variants.extend(inferred_parameter_candidates(pointer, name, context_header)[:3])
    return list(dict.fromkeys(variants))[:32]


def inferred_parameter_candidates(source, name, context_header=""):
    """Try word-sized inputs where a byte/halfword store suggests a narrow type.

    A store only uses the low bits of an argument register. It cannot establish
    that the caller supplied a narrow C parameter, especially when other code
    tests the whole register. These are candidates, not recovered type facts.
    Reviewed signatures and parameters with non-m2c names are left alone.
    """
    if re.search(r"\b" + re.escape(name) + r"\s*\(", context_header):
        return []
    signature = re.search(r"\b" + re.escape(name) + r"\(([^()]*)\)\s*\{", source)
    if not signature:
        return []
    parameters = [part.strip() for part in signature[1].split(",")]
    narrow = []
    for index, declaration in enumerate(parameters):
        parameter = re.fullmatch(r"(.+?)\s*\b(arg\d+)\s*", declaration)
        if not parameter:
            return []
        kind, argument = parameter.groups()
        kind = kind.strip()
        if not ("*" in kind or re.fullmatch(r"(?:M2C_UNK(?:8|16|32)?|[su](?:8|16|32)|s32_bool|"
                                           r"(?:(?:signed|unsigned)\s+)?(?:char|short(?:\s+int)?|int|long(?:\s+int)?)|unsigned|signed)", kind)):
            return []
        if re.fullmatch(r"(?:[su](?:8|16)|M2C_UNK(?:8|16)|(?:(?:signed|unsigned)\s+)?(?:char|short(?:\s+int)?))", kind):
            narrow.append((index, argument, kind.startswith(("u", "unsigned"))))
    if not narrow:
        return []
    variants = []
    for index, argument, unsigned in narrow:
        for kind in ("unsigned int", "int") if unsigned else ("int", "unsigned int"):
            changed = list(parameters)
            changed[index] = f"{kind} {argument}"
            variants.append(changed)
    if len(narrow) > 1:
        for mode in ("preserve", "int", "unsigned int"):
            changed = list(parameters)
            for index, argument, unsigned in narrow:
                kind = ("unsigned int" if unsigned else "int") if mode == "preserve" else mode
                changed[index] = f"{kind} {argument}"
            variants.append(changed)
    return list(dict.fromkeys(source[:signature.start(1)] + ", ".join(parts) + source[signature.end(1):]
                              for parts in variants))
