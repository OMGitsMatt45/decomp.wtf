"""Bounded N64 function reflow with a relocation inventory and an exact baseline.

Copied into a standalone export as shiftable.py. Only the selected uncompressed
text window moves; cartridge ranges, initialized data, BSS and entry stay pinned.
"""

import hashlib
import json
from pathlib import Path
import re
import struct
import shutil

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
    if b["platform"] != "n64":
        raise ValueError("function reflow requires an N64 cartridge")
    code = [s for s in b["segments"] if s["kind"] == "code"]
    segment = next((s for s in code if s["name"] == module), None) if module else code[0] if len(code) == 1 else None
    if segment is None:
        raise ValueError("select a reviewed code module for function reflow")
    if segment["name"] not in b.get("reflow", {}):
        raise ValueError("function reflow needs a reviewed layout with an explicit text_end and zero reserve")
    if module is not None and segment["name"] != module:
        raise ValueError("the requested resident module does not exist")
    functions = sorted((f for f in b["functions"] if f["seg"] == segment["name"]), key=lambda f: f["vram"])
    if not functions:
        raise ValueError("the selected module has no discovered functions")
    original = (root / b["image"]).read_bytes()
    first = functions[0]["vram"]
    if first != segment["vram"]:
        raise ValueError("function reflow needs a discovered function at the reviewed module start")
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
        at = segment["start"] + address - segment["vram"] + size - 4
        last = int.from_bytes(original[at:at + 4], 'big')
        op = last >> 26
        if op in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23) or (op == 0 and last & 63 in (8, 9)) or \
                (op == 17 and (last >> 21) & 31 == 8):
            raise ValueError("a reviewed function boundary truncates a MIPS delay slot")
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
    if segment["start"] == 0x1000 and first < entry < limit:
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
    owners = {provides[f["name"]]: f["seg"] for f in b["functions"]}
    for segment in b["segments"]:
        owners.update({obj: segment["name"] for obj in segment.get("objects", [])})
        owners.update({p["obj"]: segment["name"] for p in segment.get("pieces", []) + segment.get("bss", [])})
    name = window["segment"]["name"]
    groups = b.get("exclusive_groups", {})
    hidden = {owner for owner, group in groups.items() if owner != name and group == groups.get(name)}
    excluded = {f["name"] for f in b["functions"] if f["seg"] in hidden}
    excluded.update(symbol for owner, symbols in b.get("module_symbols", {}).items() if owner in hidden for symbol in symbols)
    addresses = {**b["symbols"], **{f["name"]: f["vram"] for f in b["functions"] if f["seg"] not in hidden}}
    for owner, symbols in b.get("module_symbols", {}).items():
        if owner not in hidden:
            addresses.update(symbols)
    addresses = {symbol: address for symbol, address in addresses.items() if symbol not in excluded}
    for path in (root / "asm/data").glob("**/*.s"):
        obj = "build/" + path.relative_to(root).with_suffix(".o").as_posix()
        if owners.get(obj) in hidden:
            continue
        for label, address in re.findall(r"\.word\s+(\.L([0-9A-Fa-f]{8}))\b", path.read_text(encoding="utf-8")):
            addresses.setdefault(label, int(address, 16))
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
        if owners.get(obj) in hidden:
            continue
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
                    if rtype:
                        relocated.setdefault(section.name, set()).add(offset)
                    relocations.append({"object": obj, "section": section.name, "offset": offset,
                                        "type": rtype, "symbol": symbol.name})
                    if rtype not in ALLOWED_RELOCATIONS:
                        hazards.append(f"unsupported MIPS relocation {rtype} in {source}")
                    if symbol['st_shndx'] == 'SHN_ABS' and first < symbol['st_value'] < end:
                        hazards.append(f"fixed absolute relocation target {symbol.name} in {source}")
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
    (root / "build/shiftable-result.json").unlink(missing_ok=True)
    if b.get("format", "matching") != "shiftable":
        raise ValueError("export a shiftable N64 project first; the matching format keeps fixed addresses")
    builder.ASSEMBLY_ONLY = True
    try:
        if not builder.build():
            raise ValueError("the original assembly baseline no longer rebuilds exactly")
        _, original_objects = builder.objects()
    finally:
        builder.ASSEMBLY_ONLY = False
    selected = [module] if module else list(b.get("reflow", {}))
    if not selected:
        raise ValueError("function reflow needs reviewed modules with explicit text_end and zero reserve")
    windows = [plan(builder, original_objects, name) for name in selected]
    from decompnet.rom.n64_crc import identify, update
    original = (root / (b.get("container", {}).get("image") or b["image"])).read_bytes()
    cartridge_cic = identify(original, cic)
    todo, provides = builder.objects()
    builder.build_objects(todo)
    moved = {f["name"] for window in windows for f in window["functions"]}
    for window in windows:
        for function in window["functions"]:
            name = function["name"]
            if not builder.c_source(function):
                trim_reserve(root / provides[name], window["sizes"][name])
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
                raise ValueError("source outside the selected moving windows must still match: " + why)
    reports, locations, module_aliases = [], {f["name"]: f["vram"] for f in b["functions"]}, {}
    for window in windows:
        report, aliases = inventory(builder, todo, provides, window, original_objects)
        cursor = window["start"]
        for index, function in enumerate(window["functions"]):
            name = function["name"]
            size = len(sections(root / provides[name]).get(".text", b""))
            if not size or size % 4:
                raise ValueError("moving functions need a nonempty word-aligned text section")
            if index:
                cursor += window["padding"][name]
            locations[name] = cursor
            cursor += size
        if cursor > window["end"]:
            raise ValueError(f"{report['module']}: function growth exceeds the reviewed code reserve by {cursor - window['end']} bytes")
        report.update(functions={f["name"]: locations[f["name"]] for f in window["functions"]},
                      used_growth=cursor - (window["end"] - window["reserve"]))
        reports.append(report)
        for alias, (owner, offset) in aliases.items():
            value = locations[owner] + offset
            if alias in locations and locations[alias] != value:
                raise ValueError("a moving alias conflicts with another module's function identity")
            module_aliases.setdefault(alias, {})[window["segment"]["name"]] = value
    report = dict(reports[0]) if len(reports) == 1 else {"format": 2, "modules": reports,
             "relocations": [r for item in reports for r in item["relocations"]], "hazards": []}
    (root / "build/relocations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if audit_only:
        print("shiftable inventory verified: build/relocations.json")
        return True
    # Original gaps inside reviewed text windows are zero padding. Placement
    # accounts for them explicitly; their former absolute positions must not
    # collide with the moved functions.
    gaps = [gap for gap in builder.fill_gaps(original_objects) if not any(
            gap[2] == w["segment"]["name"] and w["start"] <= gap[0] < w["end"] for w in windows)]
    scripts = {}
    object_owners = {provides[f["name"]]: f["seg"] for f in b["functions"]}
    for segment in b["segments"]:
        object_owners.update({obj: segment["name"] for obj in segment.get("objects", [])})
        object_owners.update({p["obj"]: segment["name"] for p in segment.get("pieces", []) + segment.get("bss", [])})
    for segment in b["segments"]:
        name = segment["name"]
        script = builder.linker_script(provides, gaps, name)
        window = next((w for w in windows if w["segment"]["name"] == name), None)
        if window:
            base = segment["vram"]
            for function in window["functions"]:
                obj = builder.object_pattern(provides[function["name"]])
                pattern = r"\. = 0x" + f"{function['vram'] - base:X}" + r"; " + re.escape(obj) + r"\(\.text\)"
                replacement = f". = 0x{locations[function['name']] - base:X}; {obj}(.text)"
                script, count = re.subn(pattern, lambda _: replacement, script)
                if count != 1:
                    raise ValueError("the export's function placement no longer matches its reviewed layout")
        # Independent links use the same final locations for resident calls,
        # pointers and qualified overlay references, even across separate ELFs.
        bindings = dict(locations)
        for alias, values in module_aliases.items():
            if name in values:
                bindings[alias] = values[name]
            elif len(set(values.values())) == 1:
                bindings[alias] = next(iter(values.values()))
            elif any(r["symbol"] == alias and object_owners.get(r["object"]) == name
                     for item in reports for r in item["relocations"]):
                raise ValueError(f"{name} references ambiguous overlay alias {alias}; use a module-qualified symbol")
        for symbol, address in bindings.items():
            pattern = r'(?m)^"?' + re.escape(symbol) + r'"? = 0x[0-9A-Fa-f]+;'
            script = re.sub(pattern, lambda _, s=symbol, a=address: f'"{s}" = 0x{a:X};', script)
        scripts[name] = script
    builder.build_modules(provides, gaps, scripts=scripts, destination="build/mod-analysis.z64")
    if len(windows) == 1 and sum(s["kind"] == "code" for s in b["segments"]) == 1:
        name = windows[0]["segment"]["name"]
        shutil.copyfile(root / f"build/modules/{name}.elf", root / "build/mod.elf")
        (root / "build/mod.ld").write_text(scripts[name], encoding="utf-8")
    candidate = (root / "build/mod-analysis.z64").read_bytes()
    recompressed = []
    if container := b.get("container"):
        from decompnet.rom.n64_layout import repack
        candidate, recompressed = repack(original, container["layout"], candidate)
    if len(candidate) != len(original):
        raise ValueError("a shiftable build changed pinned cartridge file extents")
    candidate = update(candidate, cartridge_cic)
    output.write_bytes(candidate)
    report.update(output="build/mod.z64", output_sha256=hashlib.sha256(candidate).hexdigest(),
                  functions={name: address for name, address in locations.items() if name in moved},
                  cartridge_checksums_updated=True, cic=cartridge_cic, recompressed=recompressed)
    (root / "build/shiftable-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("shiftable: build/mod.z64; original baseline verified; function locations and fixups in build/shiftable-result.json")
    return True
