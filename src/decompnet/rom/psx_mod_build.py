"""Build changed PS1 C/C++ in fixed function slots after an exact baseline.

Copied into standalone projects. Function/data addresses and disc file sizes
stay fixed. Changed objects cannot introduce owned data, BSS or helper functions.
"""

import hashlib
import json
from pathlib import Path
import shutil

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def _slot(builder, fn, image):
    from decompnet.rom import split
    parsed = split.parse_function(builder.ROOT / fn["asm"], fn["seg"], False)
    if parsed is None:
        raise ValueError("a PS1 mod needs an instruction-backed function target")
    split._complete_delay_slot(parsed, image, False)
    size = parsed.size
    start = fn["rom"]
    segment = next((s for s in builder.B["segments"] if s["name"] == fn["seg"] and s["kind"] == "code"), None)
    if not segment or start is None or fn["vram"] != segment["vram"] + start - segment["start"] or \
            not segment["start"] <= start < start + size <= (segment["end"] or len(image)):
        raise ValueError("the PS1 function slot disagrees with its module/file extent")
    for other in builder.B["functions"]:
        if other is not fn and other["seg"] == fn["seg"] and start <= other["rom"] < start + size:
            raise ValueError("overlapping PS1 function identities require layout review before source changes")
    return size


def _link(builder, fn, obj, size):
    from decompnet.elfobj import _function_symbols
    with obj.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_MIPS":
            raise ValueError("PS1 mod objects must be little-endian MIPS ELF32")
        functions = _function_symbols(elf)
        if set(functions) != {fn["name"]}:
            raise ValueError("a changed PS1 source object must define only its selected function")
        shndx, offset, _ = functions[fn["name"]]
        if offset or elf.get_section(shndx).name != ".text":
            raise ValueError("a changed PS1 function must begin its object's .text section")
        text = elf.get_section(shndx)
        if not 0 < text["sh_size"] <= size or text["sh_size"] % 4:
            raise ValueError(f"{fn['name']}: changed code exceeds its fixed {size}-byte function slot")
        extra = [s.name for s in elf.iter_sections() if s["sh_flags"] & 2 and s["sh_size"] and s.name != ".text"
                 and s.name not in (".reginfo", ".MIPS.abiflags", ".MIPS.options", ".pdr")]
        symbols = elf.get_section_by_name(".symtab")
        if extra or any(s["st_shndx"] == "SHN_COMMON" for s in symbols.iter_symbols()):
            raise ValueError("changed PS1 functions may reference pinned globals but cannot add owned data/BSS: " + ", ".join(extra))
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection) and any(r["r_info_type"] not in (0, 2, 4, 5, 6, 7, 10) for r in section.iter_relocations()):
                raise ValueError("unsupported MIPS relocation in a changed PS1 object")
    bindings = dict(builder.B["symbols"])
    bindings.update({f["name"]: f["vram"] for f in builder.B["functions"]})
    for module in builder.B.get("module_symbols", {}).values():
        for name, address in module.items():
            bindings.setdefault(name, address)
    bindings.update(builder.B.get("module_symbols", {}).get(fn["seg"], {}))
    bindings.pop(fn["name"], None)
    relative = obj.relative_to(builder.ROOT).as_posix()
    script, linked = obj.with_suffix(".ld"), obj.with_suffix(".elf")
    gp = builder.B.get("psx_modules", {}).get(fn["seg"], {}).get("gp", builder.B.get("gp", 0))
    text = f"SECTIONS {{ .text 0x{fn['vram']:X} : SUBALIGN(4) {{ {builder.object_pattern(relative)}(.text) }} "
    text += f"/DISCARD/ : {{ {builder.DISCARD} }} }}\n_gp = 0x{gp:X};\n"
    text += "\n".join(f'"{name}" = 0x{address:X};' for name, address in sorted(bindings.items())) + "\n"
    script.write_text(text, encoding="utf-8")
    builder.run([builder.binutils("ld"), "-EL", "-N", "-T", script.relative_to(builder.ROOT).as_posix(),
                 "-o", linked.relative_to(builder.ROOT).as_posix(), relative])
    with linked.open("rb") as stream:
        section = ELFFile(stream).get_section_by_name(".text")
        if section["sh_addr"] != fn["vram"]:
            raise ValueError("linked PS1 function moved from its original entry address")
        data = section.data()
    if not 0 < len(data) <= size:
        raise ValueError("linked PS1 code exceeds its original function slot")
    return data + bytes(size - len(data))


def _interior_references(builder, changed, image):
    """Fixed entry addresses do not protect references into changed bodies."""
    aliases = dict(builder.B["symbols"])
    for values in builder.B.get("module_symbols", {}).values():
        aliases.update(values)
    for fn, size in changed:
        lo, hi = fn["vram"], fn["vram"] + size
        if any(lo < value < hi for value in aliases.values()):
            raise ValueError(f"{fn['name']}: an interior symbol needs review before changing the function body")
        for at in range(0, len(image) - 3, 4):
            if fn["rom"] <= at < fn["rom"] + size:
                continue
            if lo < int.from_bytes(image[at:at + 4], "little") < hi:
                raise ValueError(f"{fn['name']}: an interior pointer needs review before changing the function body")
        for other in builder.B["functions"]:
            if other["seg"] != fn["seg"] or other is fn:
                continue
            from decompnet.rom.split import parse_function
            parsed = parse_function(builder.ROOT / other["asm"], other["seg"], False)
            for line in parsed.lines if parsed else []:
                opcode = line.word >> 26
                target = None
                if opcode in (2, 3):
                    target = ((line.vram + 4) & 0xF0000000) | ((line.word & 0x3FFFFFF) << 2)
                elif opcode in (1, 4, 5, 6, 7):
                    value = line.word & 0xFFFF
                    target = line.vram + 4 + 4 * (value - 0x10000 if value & 0x8000 else value)
                if target is not None and lo < target < hi:
                    raise ValueError(f"{fn['name']}: an interior branch target needs layout review")


def build(builder):
    if builder.B["platform"] != "psx":
        raise ValueError("fixed-slot mod builds require a PS1 project")
    root, meta = builder.ROOT, builder.B
    destination = root / "build/psx-mod"
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    report = root / "build/psx-mod-result.json"
    report.unlink(missing_ok=True)
    try:
        builder.ASSEMBLY_ONLY = True
        try:
            if not builder.build():
                raise ValueError("the original PS1 assembly baseline no longer rebuilds exactly")
        finally:
            builder.ASSEMBLY_ONLY = False
        original = (root / meta["image"]).read_bytes()
        modified, changed = bytearray(original), []
        for fn in meta["functions"]:
            source = builder.c_source(fn)
            if not source:
                continue
            compiled = builder.compile_function(builder.build_config(fn), source)
            if not compiled.ok:
                raise ValueError("compiling " + source + " failed:\n" + compiled.log)
            if builder.validate(fn, compiled.obj) is None:
                continue
            obj = destination / "objects" / (fn["name"] + ".o")
            obj.parent.mkdir(exist_ok=True)
            obj.write_bytes(compiled.obj)
            builder.trim(obj)
            size = _slot(builder, fn, original)
            data = _link(builder, fn, obj, size)
            if data != original[fn["rom"]:fn["rom"] + size]:
                changed.append((fn, size))
                modified[fn["rom"]:fn["rom"] + size] = data
        _interior_references(builder, changed, original)
        image = destination / "program.exe"
        image.write_bytes(modified)
        outputs, media_result = [image], None
        if disc := meta.get("disc"):
            layout = disc["layout"]
            media = layout.get("media")
            if media and media["kind"] == "cue":
                primary = destination / "disc" / media["primary"]
            else:
                primary = destination / ("disc" + Path(disc["output"]).suffix)
            from decompnet.rom.psx_modify import rebuild
            media_result = rebuild(root / disc["image"], bytes(modified), layout, primary)
            outputs = [primary]
            if media and media["kind"] == "cue":
                from decompnet.rom.psx_media import companions
                companions(root / disc["image"], layout, destination / "disc")
                outputs += [destination / "disc" / item["name"] for item in media["companions"]]
        from decompnet.rom.psx_disc import digest
        artifacts = []
        for path in outputs:
            with path.open("rb") as stream:
                size, sha = digest(stream)
            artifacts.append({"output": path.relative_to(root).as_posix(), "size": size, "sha256": sha})
        report.write_text(json.dumps({"format": 1, "baseline_identical": True, "mode": "fixed-slots",
            "changed_functions": [fn["name"] for fn, _ in changed], "disc": media_result, "artifacts": artifacts}, indent=2), encoding="utf-8")
        print(f"modified: {len(changed)} changed PS1 functions; original baseline verified; outputs in build/psx-mod-result.json")
        return True
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        report.unlink(missing_ok=True)
        raise
