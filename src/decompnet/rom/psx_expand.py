"""Link changed PS1 functions, helpers and data into reviewed loaded space.

Original function symbols become absolute entry addresses in the mod objects.
All calls and function pointers therefore retain their original identities;
the entry stubs jump to the separately recorded linked bodies.
"""

from collections import defaultdict
import struct

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def _pin_section_references(elf, raw, shndx, offset, function_index, symbols):
    """Period GCC also expresses function addresses as .text + an offset."""
    from decompnet.elfobj import _section_target
    for section in elf.iter_sections():
        if not isinstance(section, RelocationSection):
            continue
        owner = elf.get_section(section["sh_info"])
        rows = []
        for index, relocation in enumerate(section.iter_relocations()):
            kind, at = relocation["r_info_type"], relocation["r_offset"]
            if section.is_RELA():
                raise ValueError("PS1 mod objects require MIPS REL relocations")
            word = int.from_bytes(owner.data()[at:at + 4], "little")
            mask = 0x3FFFFFF if kind == 4 else 0xFFFF if kind in (5, 6, 7, 10) else 0xFFFFFFFF
            rows.append({"type": kind, "off": at, "value": word & mask, "mask": mask, "word": word,
                         "symidx": relocation["r_info_sym"], "symtab": symbols, "rela": False, "index": index})
        paired = {}
        for index, row in enumerate(rows):
            symbol = symbols.get_symbol(row["symidx"])
            if row["type"] != 5 or symbol["st_info"]["type"] != "STT_SECTION" or symbol["st_shndx"] != shndx:
                continue
            register = row["word"] >> 16 & 31
            end = next((i for i in range(index + 1, len(rows)) if rows[i]["type"] == 5 and rows[i]["word"] >> 16 & 31 == register), len(rows))
            lows = [i for i in range(index + 1, end) if rows[i]["type"] == 6 and rows[i]["symidx"] == row["symidx"]
                    and rows[i]["word"] >> 21 & 31 == register]
            if not lows:
                raise ValueError("unpaired section-relative PS1 function address needs review")
            targets = [(row["value"] << 16) + (rows[i]["value"] - (65536 if rows[i]["value"] & 32768 else 0)) for i in lows]
            if offset in targets and any(t != offset for t in targets):
                raise ValueError("shared high-half PS1 function addresses need review")
            paired[index] = targets[0]
            for i, target in zip(lows, targets):
                paired[i] = target
        for index, row in enumerate(rows):
            symbol = symbols.get_symbol(row["symidx"])
            if symbol["st_info"]["type"] != "STT_SECTION" or symbol["st_shndx"] != shndx:
                continue
            if row["type"] in (5, 6) and index not in paired:
                raise ValueError("unpaired section-relative PS1 function address needs review")
            if row["type"] == 7:
                raise ValueError("GP-relative PS1 function addresses need explicit entry-symbol review")
            target = paired.get(index) if row["type"] in (5, 6) else _section_target("mips", rows, index)
            if target == offset:
                kind = row["type"]
                struct.pack_into("<I", raw, section["sh_offset"] + row["index"] * section["sh_entsize"] + 4,
                                 function_index << 8 | kind)
                struct.pack_into("<I", raw, owner["sh_offset"] + row["off"], row["word"] & ~row["mask"])


def link(builder, objects, reserves, original, slot):
    from decompnet.elfobj import _function_symbols
    groups = defaultdict(list)
    for fn, obj in objects:
        groups[fn["seg"]].append((fn, obj))
    result, records, changed = bytearray(original), [], []
    pinned = {**builder.B["symbols"], **{f["name"]: f["vram"] for f in builder.B["functions"]}}
    for values in builder.B.get("module_symbols", {}).values():
        for name, address in values.items():
            pinned.setdefault(name, address)
    for module, items in groups.items():
        reserve = reserves[module]
        lo, hi = reserve["offset"], reserve["offset"] + reserve["size"]
        sizes, offsets, defined = {}, {}, set()
        for fn, obj in items:
            sizes[fn["name"]] = slot(builder, fn, original)
            if sizes[fn["name"]] < 8:
                raise ValueError("PS1 function growth requires room for an entry jump and its delay slot")
            if fn["rom"] < hi and lo < fn["rom"] + sizes[fn["name"]]:
                raise ValueError("reviewed PS1 mod space overlaps changed function code")
            raw = bytearray(obj.read_bytes())
            with obj.open("rb") as stream:
                elf = ELFFile(stream)
                if elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_MIPS":
                    raise ValueError("PS1 mod objects must be little-endian MIPS ELF32")
                functions = _function_symbols(elf)
                if fn["name"] not in functions:
                    raise ValueError("a changed PS1 object must define its selected function")
                shndx, offset, _ = functions[fn["name"]]
                if elf.get_section(shndx).name != ".text" or offset % 4:
                    raise ValueError("a changed PS1 function must use an aligned .text body")
                offsets[fn["name"]] = offset
                for section in elf.iter_sections():
                    if section["sh_flags"] & 2 and section["sh_size"] and section.name not in (
                            ".text", ".data", ".sdata", ".rodata", ".rdata", ".lit4", ".lit8", ".bss", ".sbss",
                            ".reginfo", ".MIPS.abiflags", ".MIPS.options", ".pdr") and not section.name.startswith(
                                (".text.", ".data.", ".rodata.", ".bss.", ".sdata.", ".sbss.")):
                        raise ValueError("unsupported allocated PS1 mod section: " + section.name)
                    if isinstance(section, RelocationSection) and any(r["r_info_type"] not in (0, 2, 4, 5, 6, 7, 10)
                                                                 for r in section.iter_relocations()):
                        raise ValueError("unsupported MIPS relocation in a changed PS1 object")
                symbols = elf.get_section_by_name(".symtab")
                for index, symbol in enumerate(symbols.iter_symbols()):
                    if symbol.name == fn["name"] and symbol["st_shndx"] == shndx:
                        _pin_section_references(elf, raw, shndx, offset, index, symbols)
                        at = symbols["sh_offset"] + index * symbols["sh_entsize"]
                        struct.pack_into("<I", raw, at + 4, fn["vram"])
                        struct.pack_into("<H", raw, at + 14, 0xFFF1)  # SHN_ABS: preserve calls and address identity
                    elif symbol.name and symbol["st_shndx"] != "SHN_UNDEF" and symbol.name in pinned and \
                            symbol["st_info"]["type"] not in ("STT_FILE", "STT_SECTION"):
                        raise ValueError("a new PS1 helper/data definition collides with a pinned symbol: " + symbol.name)
                    if symbol["st_shndx"] != "SHN_UNDEF" and symbol["st_info"]["bind"] != "STB_LOCAL":
                        if symbol.name in defined:
                            raise ValueError("duplicate PS1 mod definition: " + symbol.name)
                        defined.add(symbol.name)
            obj.write_bytes(raw)
        bindings = {**pinned, **builder.B.get("module_symbols", {}).get(module, {})}
        gp = builder.B.get("psx_modules", {}).get(module, {}).get("gp", builder.B.get("gp", 0))
        target = items[0][1].parent / (module + "-arena")
        script, linked = target.with_suffix(".ld"), target.with_suffix(".elf")
        lines = [f"SECTIONS {{ .arena 0x{reserve['start']:X} : SUBALIGN(4) {{"]
        for index, (fn, obj) in enumerate(items):
            pattern = builder.object_pattern(obj.relative_to(builder.ROOT).as_posix())
            lines.append(f"__psx_body_{index} = .; {pattern}(.text) {pattern}(.text.*)")
        lines.append(". = ALIGN(16);")
        for _, obj in items:
            pattern = builder.object_pattern(obj.relative_to(builder.ROOT).as_posix())
            lines.append(f"{pattern}(.rodata .rodata.* .rdata .lit4 .lit8 .data .data.* .sdata .sdata.*)")
        lines.append(". = ALIGN(16);")
        for _, obj in items:
            pattern = builder.object_pattern(obj.relative_to(builder.ROOT).as_posix())
            lines.append(f"{pattern}(.bss .bss.* .sbss .sbss.* COMMON)")
        lines.extend([f"}} /DISCARD/ : {{ {builder.DISCARD} }} }}", f"_gp = 0x{gp:X};"])
        lines += [f'"{name}" = 0x{address:X};' for name, address in sorted(bindings.items()) if name not in defined]
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        builder.run([builder.binutils("ld"), "-EL", "-N", "-T", script.relative_to(builder.ROOT).as_posix(), "-o",
                     linked.relative_to(builder.ROOT).as_posix(), *[o.relative_to(builder.ROOT).as_posix() for _, o in items]])
        with linked.open("rb") as stream:
            elf = ELFFile(stream)
            arena = elf.get_section_by_name(".arena")
            if arena["sh_addr"] != reserve["start"] or arena["sh_type"] != "SHT_PROGBITS":
                raise ValueError("PS1 mod space must be initialized in its original loaded extent")
            data = arena.data()
            if not 0 < len(data) <= reserve["size"]:
                raise ValueError("changed PS1 code/data exceeds its reviewed mod space")
            result[lo:lo + len(data)] = data
            symbols = elf.get_section_by_name(".symtab")
            addresses = {s.name: s["st_value"] for s in symbols.iter_symbols()}
            bodies = []
            for index, (fn, _) in enumerate(items):
                body = addresses[f"__psx_body_{index}"] + offsets[fn["name"]]
                if body >> 28 != (fn["vram"] + 4) >> 28 or not reserve["start"] <= body < reserve["start"] + len(data):
                    raise ValueError("PS1 mod body is outside its entry jump's address range")
                jump = (0x08000000 | (body >> 2 & 0x3FFFFFF)).to_bytes(4, "little")
                size = sizes[fn["name"]]
                result[fn["rom"]:fn["rom"] + size] = jump + bytes(size - 4)
                bodies.append({"function": fn["name"], "entry": fn["vram"], "body": body})
                changed.append((fn, size))
        records.append({"module": module, "start": reserve["start"], "capacity": reserve["size"], "used": len(data), "bodies": bodies})
    return bytes(result), changed, records
