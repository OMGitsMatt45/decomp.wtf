#!/usr/bin/env python3
"""Generate ROM configuration using the linked overlay's actual BSS boundaries.

dsd 0.12.1 rounds overlay BSS ends to 32 bytes even when its linker symbols
describe a smaller extent. Use those symbols, without changing the reference ROM
or its comparison, so genuine changes to linked BSS still change the output.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml
from elftools.elf.elffile import ELFFile


def fields(node):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("expected a toolkit YAML mapping")
    return {key.value: value for key, value in node.value}


def overlay_extents(args, config, output) -> None:
    if not config.get("overlays"):
        return
    path = output / "arm9_overlays.yaml"
    # Edit YAML nodes so toolkit enum tags (including DS Protect metadata) and
    # every unrelated value survive without constructing arbitrary YAML objects.
    document = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    with args.elf.open("rb") as stream:
        table = ELFFile(stream).get_section_by_name(".symtab")
        symbols = {s.name: s["st_value"] for s in table.iter_symbols()}
    modules = {int(m["id"]): m for m in config["overlays"]}
    layout = (args.config.parent / config["rom_config"]).parent / "retained_layout.json"
    absent = json.loads(layout.read_text(encoding="utf-8")).get("absent_arm9_constructors", {}) if layout.is_file() else {}
    for entry in fields(document)["overlays"].value:
        overlay = fields(entry)
        overlay_id = int(overlay["id"].value)
        module = modules[overlay_id]
        delinks = (args.config.parent / module["delinks"]).read_text(encoding="utf-8")
        sections = []
        for line in delinks.splitlines():
            text = line.split("//", 1)[0].strip()
            if text.endswith(":"):
                break  # only the module section definitions, before source files
            match = re.match(r"(\S+).*\bkind:bss\b", text)
            if match:
                prefix = f"OV{overlay_id:03}_{match[1].lstrip('.').upper()}"
                sections.append((symbols[prefix + "_START"], symbols[prefix + "_END"]))
        if sections:
            start, end = min(s for s, _ in sections), max(e for _, e in sections)
            if end < start or start - int(overlay["base_address"].value) != int(overlay["code_size"].value):
                raise ValueError(f"inconsistent linked BSS boundaries for overlay {overlay_id}")
            overlay["bss_size"].value = str(end - start)
        else:
            overlay["bss_size"].value = "0"
        if str(overlay_id) in absent:
            original = absent[str(overlay_id)]
            if int(overlay["ctor_start"].value) != original["start"] or int(overlay["ctor_end"].value) != original["end"]:
                raise ValueError(f"linked absent-constructor terminator moved for overlay {overlay_id}")
            overlay["ctor_start"].value = overlay["ctor_end"].value = "0"
    path.write_text(yaml.serialize(document, Dumper=yaml.SafeDumper), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsd")
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = yaml.load(args.config.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    output = (args.config.parent / config["main_module"]["object"]).parent
    complete = False
    try:
        subprocess.run([args.dsd, "rom", "config", "--elf", str(args.elf), "--config", str(args.config)], check=True)
        overlay_extents(args, config, output)
        complete = True
    finally:
        if not complete:
            (output / "rom_config.yaml").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
