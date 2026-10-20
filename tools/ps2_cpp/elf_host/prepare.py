"""Generate metadata for an experimental Windows host of original i386 EE tools.

Compiler code is not translated or replaced. The generated Windows program
maps its load segments and binds the original dynamic libc imports. Only the
driver's libiberty process-launch helpers receive explicit host ABI detours.
This is investigation tooling, not a registered or verified compiler package.
"""

import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def generate(binary: Path, output: Path) -> dict:
    with binary.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_386" or elf["e_type"] != "ET_EXEC":
            raise ValueError("Expected a little-endian i386 ET_EXEC ELF")
        segments = [dict(address=s["p_vaddr"], offset=s["p_offset"], size=s["p_filesz"], memory=s["p_memsz"])
                    for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
        symbols = elf.get_section_by_name(".symtab")
        mains = [s["st_value"] for s in symbols.iter_symbols() if s.name == "main"] if symbols else []
        if len(mains) != 1:
            raise ValueError("Expected one original main symbol")
        relocations = []
        for section in elf.iter_sections():
            if not isinstance(section, RelocationSection) or not section["sh_flags"] & 2:
                continue
            table = elf.get_section(section["sh_link"])
            for rel in section.iter_relocations():
                symbol = table.get_symbol(rel["r_info_sym"])
                if rel["r_info_type"] not in (5, 6, 7):
                    raise ValueError(f"Unsupported i386 dynamic relocation: {rel['r_info_type']}")
                relocations.append(dict(address=rel["r_offset"], name=symbol.name,
                                        size=symbol["st_size"], kind=rel["r_info_type"],
                                        local=symbol["st_value"] if symbol["st_shndx"] != "SHN_UNDEF" else 0))
        detours = {s.name: s["st_value"] for s in symbols.iter_symbols() if s.name in ("pexecute", "pwait")}
    result = dict(sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), main=mains[0],
                  segments=segments, relocations=relocations, host_detours=detours)
    names = sorted({r["name"] for r in relocations if r["kind"] != 5})
    lines = ["/* Generated ELF metadata, never edit by hand. */"]
    lines += [f"static void missing_{i}(void) {{ unsupported({json.dumps(n)}); }}" for i, n in enumerate(names)]
    lines += [
             f"static const unsigned original_main = 0x{mains[0]:x};",
             "static const struct segment segments[] = {"]
    lines += ["  {%(address)d, %(offset)d, %(size)d, %(memory)d}," % s for s in segments]
    lines += ["};", "static const struct relocation relocations[] = {"]
    lines += [f"  {{{r['address']}, {r['size']}, {r['kind']}, {r['local']}, {json.dumps(r['name'])}, "
              + ("NULL" if r['kind'] == 5 else f"missing_{names.index(r['name'])}") + "}," for r in relocations]
    lines += ["};", f"static const unsigned pexecute_address = {detours.get('pexecute', 0)};",
              f"static const unsigned pwait_address = {detours.get('pwait', 0)};"]
    output.write_text("\n".join(lines) + "\n")
    output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.binary, args.output)
