"""Rebuild a boot utility from editable GNU assembly and explicit base ranges.

This file is copied into exports. It needs decomp.wtf's pinned GNU tools and
pyelftools, and runs on Windows as well as Linux.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from elftools.elf.elffile import ELFFile


def tools_for(arch: str) -> Path:
    from decompnet import toolchains

    tid = "gc-wii-binutils" if arch == "ppc" else "binutils-arm"
    root = toolchains.ensure(tid, log=lambda *_: None)
    return root if arch == "ppc" else root / "bin"


def command(tools: Path, arch: str, tool: str) -> str:
    name = ("powerpc-eabi-" if arch == "ppc" else "arm-none-eabi-") + tool
    return str(tools / (name + (".exe" if sys.platform == "win32" else "")))


def script(address: int, symbols: dict[str, int]) -> str:
    return "\n".join(f"PROVIDE({name} = 0x{value:X});" for name, value in symbols.items()) + f"""
SECTIONS {{
 .text 0x{address:X} : {{ *(.text .text.*) }}
 /DISCARD/ : {{ *(.comment .note* .ARM.attributes) }}
}}
"""


def declarations(symbols: dict[str, int], arch: str) -> str:
    # An odd absolute linker symbol alone is not a Thumb function symbol.
    # Without this type GNU ld inserts interworking veneers into Thumb calls.
    if arch != "arm":
        return ""
    return "".join(f".thumb_set {name}, 0x{address:X}\n" if address & 1 else
                   f".type {name}, %function\n.set {name}, 0x{address:X}\n"
                   for name, address in symbols.items() if name.startswith("__boot_"))


def linked_code(raw: bytes, address: int, size: int, name: str) -> bytes:
    elf = ELFFile(BytesIO(raw))
    allocated = [section for section in elf.iter_sections() if section["sh_flags"] & 2 and section["sh_size"]]
    if len(allocated) != 1 or allocated[0].name != ".text" or allocated[0]["sh_addr"] != address \
            or allocated[0]["sh_size"] != size:
        detail = [(s.name, hex(s["sh_addr"]), s["sh_size"]) for s in allocated]
        raise ValueError(f"assembly must own exactly its original instruction range ({hex(address)}, {size} bytes); found {detail}")
    symtab = elf.get_section_by_name(".symtab")
    symbols = symtab.get_symbol_by_name(name) if symtab is not None else None
    if not symbols or not any((s["st_value"] & ~1) == address and s["st_size"] == size
                              and s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] == elf.get_section_index(".text")
                              for s in symbols):
        raise ValueError(f"assembly needs the function label {name} at its original address and exact size")
    return allocated[0].data()


def build(root: Path, *, tools: Path | None = None) -> dict:
    from decompnet.compiler import check_gnu_assembly

    root = Path(root).resolve()
    manifest = json.loads((root / "build.json").read_text(encoding="utf-8"))
    image = (root / manifest["image"]).read_bytes()
    if hashlib.sha256(image).hexdigest() != manifest["sha256"]:
        raise ValueError("base image SHA-256 differs from this project's input")
    arch = manifest["arch"]
    tools = tools or tools_for(arch)
    output = root / "build" / manifest["output"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    flags = ["-mgekko", "-mregnames"] if arch == "ppc" else ["-mcpu=arm946e-s"]
    cursor, rebuilt = 0, bytearray()
    for index, region in enumerate(sorted(manifest["ranges"], key=lambda r: r["offset"])):
        offset, size = region["offset"], region["size"]
        if offset < cursor or offset + size > len(image):
            raise ValueError("instruction ranges overlap or extend outside the image")
        source = root / region["source"]
        text = source.read_text(encoding="utf-8")
        check_gnu_assembly(text)
        assembled = root / "build" / f"range_{index}.s"
        assembled.write_text(declarations(manifest["symbols"], arch) + text, encoding="utf-8")
        obj, elf, ldscript = (root / "build" / f"range_{index}.{suffix}" for suffix in ("o", "elf", "ld"))
        ldscript.write_text(script(region["addr"], manifest["symbols"]), encoding="utf-8")
        for argv in ([command(tools, arch, "as"), *flags, "-o", str(obj), str(assembled)],
                     [command(tools, arch, "ld"), "-T", str(ldscript), "-o", str(elf), str(obj)]):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise ValueError(f"{source.name}: {(result.stdout + result.stderr)[-2500:]}")
        code = linked_code(elf.read_bytes(), region["addr"], size, region["name"])
        # Unknown code/data and headers are explicit retained base ranges.
        rebuilt.extend(image[cursor:offset])
        rebuilt.extend(code)
        cursor = offset + size
    rebuilt.extend(image[cursor:])
    if bytes(rebuilt) != image:
        first = next(i for i, (a, b) in enumerate(zip(rebuilt, image)) if a != b)
        raise ValueError(f"rebuilt {manifest['scope']} differs at file offset 0x{first:X}")
    output.write_bytes(rebuilt)
    return {"identical": True, "scope": manifest["scope"], "size": len(rebuilt),
            "assembly_bytes": sum(r["size"] for r in manifest["ranges"]), "path": str(output)}


if __name__ == "__main__":
    try:
        result = build(Path(__file__).resolve().parent)
        print(f"identical: rebuilt {result['scope']}, {result['size']} bytes ({result['assembly_bytes']} assembly bytes)")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"error: {error}")
