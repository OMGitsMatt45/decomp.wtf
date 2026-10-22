"""Build ARM7 source units at their runtime addresses and consume only exact linked ranges.

This script is copied into standalone DS projects. It uses the installed ARM
binutils and pyelftools; no decomp.wtf installation is needed by an export.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import struct
import tempfile
from io import BytesIO
from pathlib import Path

import yaml
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.relocation import RelocationSection


def states(path):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {m[1].replace("\\", "/"): bool(re.search(r"^\s+complete\s*$", m[2], re.M))
            for m in re.finditer(r"^(\S+\.(?:c|cpp)):\s*\n((?:[ \t].*(?:\n|$)|\s*\n)*)", text, re.M)}


def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    linked = states(path.with_name("delinks.txt"))
    for unit in data["units"]:
        unit["complete"] = linked.get(unit["source"], False)
    return data


def paths(build, unit):
    relative = Path(unit["source"]).with_suffix(".o")
    return build / "arm7-targets" / relative, build / relative, build / relative.with_suffix(".raw.o")


def assembly_path(build, unit):
    return build / "arm7-asm" / Path(unit["source"]).with_suffix(".s")


def write_assembly(manifest, unit, build):
    from capstone import CS_ARCH_ARM, CS_GRP_CALL, CS_GRP_JUMP, CS_MODE_ARM, CS_MODE_THUMB, Cs
    from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

    module = manifest["modules"][unit["module"]]
    data = Path(module["binary"]).read_bytes()
    start = module["source_offset"] + unit["address"] - module["address"]
    code = data[start:start + unit["size"]]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB if unit["mode"] == "thumb" else CS_MODE_ARM)
    decoder.detail = True
    lines = [f"glabel {unit['symbol']}"]
    for offset in sorted(set(unit.get("instructions", [])) | set(unit.get("pools", []))):
        address = unit["address"] + offset
        lines.append(f".L_{address:08X}:")
        if offset in unit.get("pools", []):
            lines.append(f".word 0x{int.from_bytes(code[offset:offset + 4], 'little'):08X}")
            continue
        instruction = next(decoder.disasm(code[offset:offset + 4], address, count=1), None)
        if instruction is None:
            raise ValueError("recorded ARM7 instruction no longer decodes")
        operands = instruction.op_str
        if instruction.mnemonic.startswith("ldr") and len(instruction.operands) > 1 and \
                instruction.operands[1].type == ARM_OP_MEM and instruction.operands[1].mem.base == ARM_REG_PC:
            pc = (address + 4) & ~3 if unit["mode"] == "thumb" else address + 8
            operands = f"{instruction.reg_name(instruction.operands[0].reg)}, .L_{pc + instruction.operands[1].mem.disp:08X}"
        elif (instruction.group(CS_GRP_CALL) or instruction.group(CS_GRP_JUMP)) and \
                instruction.operands[-1].type == ARM_OP_IMM:
            target = instruction.operands[-1].imm & ~1
            operands = unit.get("call_symbols", {}).get(str(target), f".L_{target:08X}") \
                if instruction.group(CS_GRP_CALL) else f".L_{target:08X}"
        lines.append(f"{instruction.mnemonic} {operands}")
    path = assembly_path(build, unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def original_region(data, module, region):
    offset = module["source_offset"] + region["address"] - module["address"]
    if region["kind"] == "bss":
        bss = module.get("bss_address", module["address"] + module["size"])
        if not bss <= region["address"] < region["address"] + region["size"] <= bss + module["bss_size"]:
            raise ValueError("ARM7 BSS region outside the recorded module")
        return None
    if region["size"] <= 0 or offset < module["source_offset"] or \
            offset + region["size"] > module["source_offset"] + module["size"]:
        raise ValueError("ARM7 initialized region outside the recorded module")
    return data[offset:offset + region["size"]]


def regions(unit):
    return unit.get("regions") or [{"section": ".text", "kind": "code", "address": unit["address"],
                                    "size": unit["size"]}]


def script(unit):
    lines = ["SECTIONS {"]
    for region in regions(unit):
        section = region["section"]
        if section not in (".text", ".rodata", ".data", ".bss"):
            raise ValueError("unsupported ARM7 source-unit section")
        lines.append(f" {section} 0x{region['address']:X} : {{ *({section} {section}.*) }}")
    lines.append(" /DISCARD/ : { *(.comment .note* .ARM.attributes .debug* .line* .mwcats* .exceptix .exception) }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def run(command):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError((result.stdout + result.stderr)[-4000:] or "ARM7 tool failed")


def comparison_object(path):
    """Represent fully resolved bytes as section-relative ELF symbols for objdiff.

    Keep every code/data byte. The separate runtime ELF retains placement. No relocation
    is masked or re-applied: this is only the ELF envelope used by object tools.
    """
    data = bytearray(path.read_bytes())
    elf = ELFFile(BytesIO(data))
    for table in elf.iter_sections():
        if not isinstance(table, SymbolTableSection):
            continue
        for index, symbol in enumerate(table.iter_symbols()):
            section = symbol["st_shndx"]
            if section == "SHN_ABS":
                # These typed aliases guided interworking during linking. They
                # are external addresses, not functions/data owned by this unit.
                at = table["sh_offset"] + index * table["sh_entsize"] + 12
                data[at] &= 0xF0  # preserve binding, expose as STT_NOTYPE
            if isinstance(section, int) and section > 0:
                address = elf.get_section(section)["sh_addr"]
                value = symbol["st_value"]
                if value >= address:
                    struct.pack_into("<I", data, table["sh_offset"] + index * table["sh_entsize"] + 4, value - address)
    for index, section in enumerate(elf.iter_sections()):
        struct.pack_into("<I", data, elf["e_shoff"] + index * elf["e_shentsize"] + 12, 0)
    struct.pack_into("<H", data, 16, 1)  # ET_REL, with section-relative symbols
    struct.pack_into("<II", data, 24, 0, 0)  # no entrypoint or program headers
    struct.pack_into("<HH", data, 42, 0, 0)
    path.write_bytes(data)


def gnu_object(source, output):
    """Translate CodeWarrior relocation addends/mode metadata to GNU ARM ELF conventions."""
    data = bytearray(source.read_bytes())
    elf = ELFFile(BytesIO(data))
    for section_index, section in enumerate(elf.iter_sections()):
        if isinstance(section, RelocationSection):
            if not section.is_RELA():
                continue
            for index, relocation in enumerate(section.iter_relocations()):
                target = elf.get_section(section["sh_info"])
                at = target["sh_offset"] + relocation["r_offset"]
                kind, addend = relocation["r_info_type"], relocation["r_addend"]
                # GNU ARM's linker reads addends in-place even for these legacy
                # RELA records. Encode the existing explicit addend and emit REL.
                if kind == 1:  # R_ARM_PC24
                    word = struct.unpack_from("<I", data, at)[0]
                    struct.pack_into("<I", data, at, (word & 0xFF000000) | ((addend >> 2) & 0xFFFFFF))
                elif kind == 10:  # R_ARM_THM_CALL (Thumb-1 BL pair)
                    hi, lo = struct.unpack_from("<HH", data, at)
                    struct.pack_into("<HH", data, at, (hi & 0xF800) | ((addend >> 12) & 0x7FF),
                                     (lo & 0xF800) | ((addend >> 1) & 0x7FF))
                elif kind in (2, 3):  # R_ARM_ABS32, R_ARM_REL32
                    struct.pack_into("<I", data, at, addend & 0xFFFFFFFF)
                elif kind not in (0, 40):
                    raise ValueError(f"unsupported CodeWarrior ARM7 relocation type {kind}")
                struct.pack_into("<II", data, section["sh_offset"] + index * 8,
                                 relocation["r_offset"], relocation["r_info"])
            header = elf["e_shoff"] + section_index * elf["e_shentsize"]
            struct.pack_into("<I", data, header + 4, 9)  # SHT_REL
            struct.pack_into("<I", data, header + 20, section.num_relocations() * 8)
            struct.pack_into("<I", data, header + 36, 8)
        elif isinstance(section, SymbolTableSection):
            symbols = list(section.iter_symbols())
            for index, symbol in enumerate(symbols):
                if re.fullmatch(r"\$[atd](?:\..*)?", symbol.name):
                    data[section["sh_offset"] + index * section["sh_entsize"] + 12] &= 0xF0
                elif symbol["st_info"]["type"] == "STT_FUNC" and isinstance(symbol["st_shndx"], int):
                    mappings = [(s["st_value"], s.name[1]) for s in symbols if s["st_shndx"] == symbol["st_shndx"]
                                and s["st_value"] <= symbol["st_value"] and re.fullmatch(r"\$[atd](?:\..*)?", s.name)]
                    if mappings and max(mappings)[1] == "t":
                        struct.pack_into("<I", data, section["sh_offset"] + index * section["sh_entsize"] + 4,
                                         symbol["st_value"] | 1)
    output.write_bytes(data)


def make_target(manifest, unit, output, assembler, linker, build=None):
    module = manifest["modules"][unit["module"]]
    data = Path(module["binary"]).read_bytes()
    lines = [".syntax unified"]
    for region in regions(unit):
        flags = "ax" if region["kind"] == "code" else "aw" if region["kind"] in ("data", "bss") else "a"
        lines.append(f".section {region['section']},\"{flags}\"" +
                     (",%nobits" if region["kind"] == "bss" else ""))
        raw = original_region(data, module, region)
        if region["kind"] == "code":
            lines += [f".{unit['mode']}", f".global {unit['symbol']}", f".type {unit['symbol']},%function"]
            if unit["mode"] == "thumb":
                lines.append(".thumb_func")
            lines.append(f"{unit['symbol']}:")
        elif region.get("symbol"):
            lines += [f".global {region['symbol']}", f".type {region['symbol']},%object", f"{region['symbol']}:"]
        if raw is None:
            lines.append(f".space {region['size']}")
        else:
            at = 0
            instruction_offsets = set(unit.get("instructions", [])) if region["kind"] == "code" else set()
            while at < len(raw):
                if at in instruction_offsets:
                    if unit["mode"] == "arm":
                        lines.append(f".inst 0x{int.from_bytes(raw[at:at + 4], 'little'):08X}")
                        at += 4
                    else:
                        from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
                        instruction = next(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(raw[at:at + 4], 0, count=1))
                        first = int.from_bytes(raw[at:at + 2], "little")
                        if instruction.size == 4:
                            value = (first << 16) | int.from_bytes(raw[at + 2:at + 4], "little")
                            lines.append(f".inst.w 0x{value:08X}")
                        else:
                            lines.append(f".inst.n 0x{first:04X}")
                        at += instruction.size
                else:
                    lines.append(f".byte 0x{raw[at]:02X}")
                    at += 1
        symbol = unit["symbol"] if region["kind"] == "code" else region.get("symbol")
        if symbol:
            lines.append(f".size {symbol},.-{symbol}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        (work / "original.s").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (work / "unit.ld").write_text(script(unit), encoding="utf-8")
        run([assembler, "-mcpu=arm7tdmi", "-meabi=gnu", "-o", work / "original.o", work / "original.s"])
        run([linker, "-e", "0", "-T", work / "unit.ld", work / "original.o", "-o", work / "original.elf"])
        comparison_object(work / "original.elf")
        (work / "original.elf").replace(output)
    if build is not None:
        write_assembly(manifest, unit, build)


def objdiff(manifest, build, config):
    data = json.loads(config.read_text(encoding="utf-8"))
    data["units"] = [u for u in data.get("units", []) if not u.get("name", "").startswith("arm7/")]
    for unit in manifest["units"]:
        target, base, _ = paths(build, unit)
        data["units"].append({"name": unit["name"], "target_path": target.as_posix(), "base_path": base.as_posix(),
                              "metadata": {"source_path": unit["source"], "complete": unit["complete"],
                                           "virtual_address": unit["address"], "instruction_mode": unit["mode"]}})
    config.write_text(json.dumps(data, indent=2), encoding="utf-8")


def link_unit(manifest, unit, raw, output, assembler, linker):
    definitions = [".syntax unified"]
    with raw.open("rb") as stream:
        compiled = ELFFile(stream)
        if compiled.elfclass != 32 or not compiled.little_endian or compiled["e_machine"] != "EM_ARM":
            raise ValueError("ARM7 source needs a little-endian ARM ELF32 object")
        abi_flags = compiled["e_flags"]
        table = compiled.get_section_by_name(".symtab")
        defined = {s.name for s in table.iter_symbols() if s["st_shndx"] != "SHN_UNDEF"} if table else set()
    for name, info in manifest.get("symbols", {}).items():
        if name == unit["symbol"] or name in defined or not re.fullmatch(r"[A-Za-z_]\w*", name):
            continue
        definitions.append(f".global {name}")
        if info.get("mode"):
            definitions.append(f".type {name},%function")
        directive = ".thumb_set" if info.get("mode") == "thumb" else ".set"
        value = info["address"] | (1 if info.get("mode") == "thumb" else 0)
        definitions.append(f"{directive} {name},0x{value:X}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)
        (work / "symbols.s").write_text("\n".join(definitions) + "\n", encoding="utf-8")
        (work / "unit.ld").write_text(script(unit), encoding="utf-8")
        run([assembler, "-mcpu=arm7tdmi", "-meabi=gnu", "-o", work / "symbols.o", work / "symbols.s"])
        # Absolute declarations contain no instructions/data or calling ABI.
        # GNU as cannot emit the obsolete EABI-2 header used by CodeWarrior;
        # describe these declarations with their consuming object's ABI flags.
        declarations = bytearray((work / "symbols.o").read_bytes())
        struct.pack_into("<I", declarations, 36, abi_flags)
        (work / "symbols.o").write_bytes(declarations)
        gnu_object(raw, work / "compiled.o")
        run([linker, "-e", "0", "-T", work / "unit.ld", work / "compiled.o", work / "symbols.o", "-o", work / "linked.elf"])
        output.with_suffix(".linked.elf").write_bytes((work / "linked.elf").read_bytes())
        comparison_object(work / "linked.elf")
        (work / "linked.elf").replace(output)


def exact_regions(path, module, unit, original):
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if not elf.little_endian or elf["e_machine"] != "EM_ARM":
            raise ValueError("ARM7 source object must be little-endian ARM ELF")
        allocated = {s.name: s for s in elf.iter_sections() if s["sh_flags"] & 2 and s["sh_size"]}
        expected = {r["section"]: r for r in regions(unit)}
        if set(allocated) != set(expected):
            raise ValueError(f"ARM7 unit {unit['source']} owns unexpected or missing initialized/BSS sections")
        table = elf.get_section_by_name(".symtab")
        functions = table.get_symbol_by_name(unit["symbol"]) if table else None
        if not functions or not any(isinstance(s["st_shndx"], int) and
                                    (s["st_value"] & ~1) == unit["address"]
                                    and s["st_size"] == unit["size"]
                                    for s in functions):
            raise ValueError(f"ARM7 function {unit['symbol']} moved or changed size")
        function = next(s for s in functions if isinstance(s["st_shndx"], int) and
                        (s["st_value"] & ~1) == unit["address"] and s["st_size"] == unit["size"])
        mappings = [(s["st_value"], s.name[1]) for s in table.iter_symbols()
                    if s["st_shndx"] == function["st_shndx"] and s["st_value"] <= unit["address"]
                    and re.fullmatch(r"\$[atd](?:\..*)?", s.name)]
        mode = "thumb" if function["st_value"] & 1 or (mappings and max(mappings)[1] == "t") else "arm"
        if mode != unit["mode"]:
            raise ValueError(f"ARM7 function {unit['symbol']} changed instruction mode")
        result = []
        for name, region in expected.items():
            section = allocated[name]
            reference = original_region(original, module, region)
            if section["sh_addr"] != region["address"] or section["sh_size"] != region["size"] or \
                    (reference is None) != (section["sh_type"] == "SHT_NOBITS") or \
                    (reference is not None and section.data() != reference):
                raise ValueError(f"ARM7 unit {unit['source']} differs in {name}; source was not linked")
            if reference is not None:
                result.append((module["source_offset"] + region["address"] - module["address"], section.data()))
        return result


def merge(manifest, build, rom_config, output, dsd=None):
    """Read actual source-built ELF data for each completed unit, then update ARM7 build inputs."""
    buffers = {}
    for unit in manifest["units"]:
        if not unit["complete"]:
            continue
        module = manifest["modules"][unit["module"]]
        binary = Path(module["binary"]).resolve()
        original = binary.read_bytes()
        patches = exact_regions(paths(build, unit)[1].with_suffix(".linked.elf"), module, unit, original)
        target = buffers.setdefault(binary, bytearray(original))
        for at, data in patches:
            target[at:at + len(data)] = data
    config = yaml.safe_load(rom_config.read_text(encoding="utf-8"))
    # Protected main/copied modules use decoded reference views. Re-encode the
    # actual source-built bytes, then place them back in the original program.
    for module in manifest["modules"].values():
        binary = Path(module["binary"]).resolve()
        if not module.get("codec") or binary not in buffers:
            continue
        try:
            from . import arm7_codec
        except ImportError:
            import arm7_codec
        if not dsd:
            raise ValueError("ARM7 protection requires the pinned dsd codec")
        encoded = arm7_codec.encrypt(dsd, Path(module["codec"]), buffers.pop(binary))
        destination = Path(module["output_binary"]).resolve()
        target = buffers.setdefault(destination, bytearray(destination.read_bytes()))
        offset = module["output_offset"]
        if offset < 0 or offset + len(encoded) > len(target):
            raise ValueError("ARM7 protected output is outside the stored program")
        target[offset:offset + len(encoded)] = encoded
    output.parent.mkdir(parents=True, exist_ok=True)
    replacements = {}
    for index, (binary, data) in enumerate(buffers.items()):
        destination = output.parent / f"arm7-linked-{index}.bin"
        destination.write_bytes(data)
        replacements[binary] = destination.resolve()
    original_main = (rom_config.parent / config["arm7_bin"]).resolve()
    if original_main in replacements:
        config["arm7_bin"] = str(replacements[original_main])
    if config.get("arm7_overlays"):
        table_path = (rom_config.parent / config["arm7_overlays"]).resolve()
        document = yaml.compose(table_path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        fields = lambda node: {k.value: v for k, v in node.value}
        for overlay in fields(document)["overlays"].value:
            file = fields(overlay)["file_name"]
            binary = (table_path.parent / file.value).resolve()
            file.value = str(replacements.get(binary, binary))
        table_output = output.parent / "arm7-linked-overlays.yaml"
        table_output.write_text(yaml.serialize(document, Dumper=yaml.SafeDumper), encoding="utf-8")
        config["arm7_overlays"] = str(table_output.resolve())
    # Other config paths were relative to the original config directory.
    if output.parent.resolve() != rom_config.parent.resolve():
        raise ValueError("ARM7 merged ROM config must share the original config directory")
    output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("target", "link", "merge", "objdiff"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--source")
    parser.add_argument("--assembler")
    parser.add_argument("--linker")
    parser.add_argument("--rom-config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dsd")
    parser.add_argument("--dsd-config", type=Path)
    args = parser.parse_args()
    manifest = load(args.manifest)
    if args.command == "merge":
        merge(manifest, args.build, args.rom_config, args.output, args.dsd)
    elif args.command == "objdiff":
        if args.dsd:
            run([args.dsd, "objdiff", "--config-path", args.dsd_config, "--custom-make", "ninja"])
        objdiff(manifest, args.build, args.output)
    else:
        unit = next(u for u in manifest["units"] if u["source"] == args.source)
        target, base, raw = paths(args.build, unit)
        if args.command == "target":
            make_target(manifest, unit, target, args.assembler, args.linker, args.build)
        else:
            link_unit(manifest, unit, raw, base, args.assembler, args.linker)


if __name__ == "__main__":
    main()
