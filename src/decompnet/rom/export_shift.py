"""Bounded N64 function reflow with a relocation inventory and an exact baseline.

Copied into a standalone export as shiftable.py. Only the selected uncompressed
text window moves; cartridge ranges, initialized data, BSS and entry stay pinned.
"""

import hashlib
import json
from pathlib import Path
import re
import struct

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ALLOWED_RELOCATIONS = {0, 2, 4, 5, 6, 7, 10, 12}


def allocated(section):
    """Only game sections survive the export linker's metadata discard list."""
    return (section["sh_flags"] & 2 and section["sh_size"] and
            section["sh_type"] in ("SHT_PROGBITS", "SHT_NOBITS") and
            section.name not in (".reginfo", ".MIPS.abiflags", ".MIPS.options", ".pdr") and
            not section.name.startswith((".mdebug", ".gnu.attributes")))


def sections(path):
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 32 or elf.little_endian or elf["e_machine"] != "EM_MIPS":
            raise ValueError("shiftable N64 objects must be big-endian MIPS ELF32")
        return {s.name: s.data() for s in elf.iter_sections() if allocated(s)
                and s["sh_type"] != "SHT_NOBITS"}


def plan(builder, original_objects, module=None):
    b, root = builder.B, builder.ROOT
    if b["platform"] != "n64" or b.get("container"):
        raise ValueError("function reflow currently requires an uncompressed N64 cartridge")
    code = [s for s in b["segments"] if s["kind"] == "code"]
    if len(code) != 1:
        raise ValueError("function reflow currently requires one reviewed resident code module")
    segment = code[0]
    if segment["name"] not in b.get("reflow", {}):
        raise ValueError("function reflow needs a reviewed layout with an explicit text_end and zero reserve")
    if module is not None and segment["name"] != module:
        raise ValueError("the requested resident module does not exist")
    functions = sorted((f for f in b["functions"] if f["seg"] == segment["name"]), key=lambda f: f["vram"])
    if not functions:
        raise ValueError("the selected module has no discovered functions")
    original = (root / b["image"]).read_bytes()
    first = functions[0]["vram"]
    limit = min([p["vram"] for p in segment["pieces"] if p["vram"] >= first] +
                [segment["vram"] + (segment["end"] or len(original)) - segment["start"]])
    text_end = segment["vram"] + b["reflow"][segment["name"]]
    if not first < text_end <= limit:
        raise ValueError("the reviewed text_end is outside the moving code window")
    cursor = first
    sizes, pads = {}, {}
    for index, function in enumerate(functions):
        address = function["vram"]
        size = min(len(sections(root / original_objects[function["name"]]).get(".text", b"")), text_end - address)
        if not size or size % 4 or not cursor <= address < address + size <= limit:
            raise ValueError("function reflow needs nonoverlapping code with a recorded data boundary")
        lo = segment["start"] + cursor - segment["vram"]
        hi = segment["start"] + address - segment["vram"]
        if original[lo:hi].strip(b"\0"):
            raise ValueError("unassigned nonzero code between functions needs additional layout review")
        sizes[function["name"]] = size
        if index:
            pads[function["name"]] = address - cursor
        cursor = address + size
    if cursor != text_end:
        raise ValueError("the reviewed text_end does not end at an owned function boundary")
    lo = segment["start"] + cursor - segment["vram"]
    hi = segment["start"] + limit - segment["vram"]
    if original[lo:hi].strip(b"\0"):
        raise ValueError("function growth requires a reviewed trailing zero reserve before data")
    entry = int.from_bytes(original[8:12], "big")
    if first < entry < limit:
        raise ValueError("an entry inside a moving function window needs an explicit entry relocation")
    return {"segment": segment, "functions": functions, "start": first, "end": limit,
            "sizes": sizes, "padding": pads, "reserve": limit - cursor}


def trim_reserve(path, size):
    """Splat attaches trailing zero reserve to the last assembly function."""
    data = bytearray(path.read_bytes())
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        for index, section in enumerate(elf.iter_sections()):
            if section.name == ".text" and section["sh_size"] > size:
                if section.data()[size:].strip(b"\0"):
                    raise ValueError("reviewed text reserve contains nonzero instructions")
                for table in elf.iter_sections():
                    if isinstance(table, RelocationSection) and table["sh_info"] == index and any(
                            r["r_offset"] >= size for r in table.iter_relocations()):
                        raise ValueError("reviewed text reserve contains relocations")
                struct.pack_into(">I", data, elf["e_shoff"] + index * elf["e_shentsize"] + 20, size)
    path.write_bytes(data)


def inventory(builder, todo, provides, window, original_objects):
    """Keep every real ELF fixup; refuse unresolved absolute references into moving code."""
    b, root = builder.B, builder.ROOT
    first, end = window["start"], window["end"]
    ranges = [(f["vram"], f["vram"] + window["sizes"][f["name"]], f["name"]) for f in window["functions"]]
    addresses = {**b["symbols"], **{f["name"]: f["vram"] for f in b["functions"]}}
    for owner in b.get("module_symbols", {}).values():
        addresses.update(owner)
    relocations, hazards, aliases = [], [], {}
    changed = {f["name"] for f in window["functions"]
               if sections(root / provides[f["name"]]).get(".text") !=
               sections(root / original_objects[f["name"]]).get(".text")}
    for name, address in addresses.items():
        if not first <= address < end:
            continue
        target = next(((a, c, n) for a, c, n in ranges if a <= address < c), None)
        if target is None:
            hazards.append(f"{name} points into unowned moving-code padding")
        elif name != target[2]:
            if address != target[0] and target[2] in changed:
                hazards.append(f"{name} points inside changed function {target[2]}")
            aliases[name] = (target[2], address - target[0])
    for kind, source, obj in todo:
        with (root / obj).open("rb") as stream:
            elf = ELFFile(stream)
            relocated = {}
            for table in elf.iter_sections():
                if not isinstance(table, RelocationSection):
                    continue
                section = elf.get_section(table["sh_info"])
                if not allocated(section):
                    continue
                symbols = elf.get_section(table["sh_link"])
                for relocation in table.iter_relocations():
                    offset, rtype = relocation["r_offset"], relocation["r_info_type"]
                    symbol = symbols.get_symbol(relocation["r_info_sym"])
                    relocated.setdefault(section.name, set()).add(offset)
                    relocations.append({"object": obj, "section": section.name, "offset": offset,
                                        "type": rtype, "symbol": symbol.name})
                    if rtype not in ALLOWED_RELOCATIONS:
                        hazards.append(f"unsupported MIPS relocation {rtype} in {source}")
            for section in elf.iter_sections():
                if not allocated(section) or section["sh_type"] == "SHT_NOBITS":
                    continue
                data = section.data()
                fixed = relocated.get(section.name, set())
                if not section["sh_flags"] & 4:
                    for offset in range(0, len(data) - 3, 4):
                        value = int.from_bytes(data[offset:offset + 4], "big")
                        if first < value < end and offset not in fixed:
                            hazards.append(f"unrelocated data pointer in {source}:{section.name}+0x{offset:X}")
                    continue
                # Constant address construction must not silently survive a
                # function move. Symbolic HI16/LO16 pairs already have fixups.
                upper = {}
                owner = next((f for f in b["functions"] if provides.get(f["name"]) == obj), None)
                pc = owner["vram"] if owner else window["segment"]["vram"]
                for offset in range(0, len(data) - 3, 4):
                    word = int.from_bytes(data[offset:offset + 4], "big")
                    if first < word < end and offset not in fixed:
                        hazards.append(f"unrelocated embedded pointer in {source}:{section.name}+0x{offset:X}")
                    op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
                    if op == 15:
                        upper[rt] = (word & 0xFFFF, offset)
                        continue
                    if op in (9, 13, 32, 33, 35, 36, 37, 39, 40, 41, 43, 49, 53, 55, 57, 61, 63) and rs in upper:
                        high, at = upper[rs]
                        low = word & 0xFFFF
                        value = ((high << 16) | low) if op == 13 else ((high << 16) + (low if low < 0x8000 else low - 0x10000)) & 0xFFFFFFFF
                        if first < value < end and (at not in fixed or offset not in fixed):
                            hazards.append(f"unrelocated code address in {source}:{section.name}+0x{at:X}")
                    if op in (2, 3) and offset not in fixed:
                        target = ((pc + offset + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
                        if first < target < end:
                            hazards.append(f"unrelocated jump in {source}:{section.name}+0x{offset:X}")
                    if op in (1, 4, 5, 6, 7, 20, 21, 22, 23) or (op == 17 and rs == 8):
                        immediate = word & 0xFFFF
                        target = pc + offset + 4 + (immediate if immediate < 0x8000 else immediate - 0x10000) * 4
                        if offset not in fixed and (owner is None or not pc <= target < pc + len(data)):
                            hazards.append(f"unrelocated branch outside its function in {source}:{section.name}+0x{offset:X}")
                    if op == 0:
                        upper.pop((word >> 11) & 31, None)
                    elif op not in (2, 3, 4, 5, 6, 7, 40, 41, 43, 63):
                        upper.pop(rt, None)
    report = {"format": 1, "module": window["segment"]["name"], "window_start": first, "window_end": end,
              "available_growth": window["reserve"], "relocations": relocations,
              "aliases": {k: {"function": v[0], "offset": v[1]} for k, v in aliases.items()},
              "hazards": sorted(set(hazards))}
    (root / "build/relocations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if hazards:
        raise ValueError("function reflow needs relocation review: " + "; ".join(report["hazards"][:5]))
    return report, aliases


def build(builder, module=None, cic=None, *, audit_only=False):
    b, root = builder.B, builder.ROOT
    output = root / "build/mod.z64"
    output.unlink(missing_ok=True)
    if b.get("format", "matching") != "shiftable":
        raise ValueError("export a shiftable N64 project first; the matching format keeps fixed addresses")
    # The baseline always consumes original disassembly, independent of edits
    # to recovered source, and must reproduce every original cartridge byte.
    builder.ASSEMBLY_ONLY = True
    try:
        if not builder.build():
            raise ValueError("the original assembly baseline no longer rebuilds exactly")
        _, original_objects = builder.objects()
    finally:
        builder.ASSEMBLY_ONLY = False
    window = plan(builder, original_objects, module)
    from decompnet.rom.n64_crc import identify, update
    cartridge_cic = identify((root / b["image"]).read_bytes(), cic)
    todo, provides = builder.objects()
    builder.build_objects(todo)
    for function in window["functions"]:
        name = function["name"]
        if not builder.c_source(function):
            trim_reserve(root / provides[name], window["sizes"][name])
    moved = {f["name"] for f in window["functions"]}
    for function in b["functions"]:
        if not builder.c_source(function):
            continue
        if function["name"] in moved:
            with (root / provides[function["name"]]).open("rb") as stream:
                elf = ELFFile(stream)
                extra = [s.name for s in elf.iter_sections() if allocated(s) and s.name != ".text"]
                symbol = next((s for s in elf.get_section_by_name('.symtab').iter_symbols()
                               if s.name == function['name'] and s['st_shndx'] != 'SHN_UNDEF'), None)
                if symbol is None or not isinstance(symbol['st_shndx'], int) or symbol['st_value'] != 0 or \
                        elf.get_section(symbol['st_shndx']).name != '.text':
                    raise ValueError("a moving source object must define its selected function at the start of .text")
            if extra:
                raise ValueError("moving functions may reference pinned globals but cannot add owned data/BSS: " + ", ".join(extra))
        else:
            why = builder.validate(function, (root / provides[function["name"]]).read_bytes())
            if why:
                raise ValueError("source outside the selected moving window must still match: " + why)
    report, aliases = inventory(builder, todo, provides, window, original_objects)
    if audit_only:
        print("shiftable inventory verified: build/relocations.json")
        return True
    gaps = builder.fill_gaps(original_objects)
    script = builder.linker_script(provides, gaps)
    cursor, locations = window["start"], {}
    segment_base = window["segment"]["vram"]
    for index, function in enumerate(window["functions"]):
        name = function["name"]
        size = len(sections(root / provides[name]).get(".text", b""))
        if not size or size % 4:
            raise ValueError("moving functions need a nonempty word-aligned text section")
        if index:
            cursor += window["padding"][name]
        locations[name] = cursor
        pattern = r"\. = 0x" + f"{function['vram'] - segment_base:X}" + r"; " + re.escape(provides[name]) + r"\(\.text\)"
        replacement = f". = 0x{cursor - segment_base:X}; {provides[name]}(.text)"
        script, count = re.subn(pattern, lambda _: replacement, script)
        if count != 1:
            raise ValueError("the export's function placement no longer matches its reviewed layout")
        cursor += size
    if cursor > window["end"]:
        raise ValueError(f"function growth exceeds the reviewed code reserve by {cursor - window['end']} bytes")
    for alias, (owner, offset) in aliases.items():
        pattern = r'(?m)^"?' + re.escape(alias) + r'"? = 0x[0-9A-Fa-f]+;'
        script = re.sub(pattern, lambda _: f'"{alias}" = "{owner}" + 0x{offset:X};', script)
    (root / "build/mod.ld").write_text(script, encoding="utf-8")
    objects = sorted({obj for _, _, obj in todo} | {obj for _, obj, _ in gaps})
    builder.run([builder.binutils("ld"), *b["ld_flags"], "-T", "build/mod.ld", "-o", "build/mod.elf", *objects])
    builder.run([builder.binutils("objcopy"), "-O", "binary", "build/mod.elf", "build/mod-candidate.z64"])
    candidate = (root / "build/mod-candidate.z64").read_bytes()
    original = (root / b["image"]).read_bytes()
    if len(candidate) != len(original):
        raise ValueError("a shiftable build changed pinned cartridge file extents")
    # The boot entry stays pinned; checksum serialization is an explicit output
    # step for the modified cartridge and never affects baseline comparison.
    candidate = update(candidate, cartridge_cic)
    output.write_bytes(candidate)
    report.update(output="build/mod.z64", output_sha256=hashlib.sha256(candidate).hexdigest(), functions=locations,
                  used_growth=cursor - (window["end"] - window["reserve"]),
                  cartridge_checksums_updated=True, cic=cartridge_cic)
    (root / "build/shiftable-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("shiftable: build/mod.z64; original baseline verified; function locations and fixups in build/shiftable-result.json")
    return True
