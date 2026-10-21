"""Editable RGBDS projects with explicit code ranges and owner-supplied base bytes."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from . import gb


def export(data: bytes, out: Path, *, entries: list[gb.Address] | None = None,
           ranges: list[gb.CodeRange] | None = None) -> dict:
    info = gb.read_info(data)
    discovered, notes = gb.discover(data, entries)
    regions = sorted([*discovered, *(ranges or [])], key=lambda r: r.start.offset)
    previous_end = 0
    for region in regions:
        if region.start.offset < previous_end:
            raise gb.CartridgeError("code ranges overlap; use --entry for additional reachable code")
        previous_end = region.start.offset + region.size
        if previous_end > len(data):
            raise gb.CartridgeError("code range extends beyond this cartridge")
    # An export creates a new project. Never clobber someone's edited assembly.
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise gb.CartridgeError(f"export directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "src").mkdir()
    main = ['; RGBDS assembly. Unanalysed bytes come from your own verified base ROM.', '']
    manifest = {"format": "decompnet-gb-assembly-v1", "rgbds": "1.0.4", "rom": info,
                "code_ranges": [], "analysis_notes": notes}
    by_bank: dict[int, list[gb.CodeRange]] = {}
    for region in regions:
        by_bank.setdefault(region.start.bank, []).append(region)
    for bank in range(info["banks"]):
        cursor = bank * gb.BANK_SIZE
        bank_end = cursor + gb.BANK_SIZE
        for region in by_bank.get(bank, []):
            if cursor < region.start.offset:
                main.extend(_gap(cursor, region.start.offset - cursor))
            path = f"src/bank_{bank:03x}_{region.start.cpu:04x}.asm"
            (out / path).write_text(gb.assembly(data, region), encoding="utf-8", newline="\n")
            main += [f'INCLUDE "{path}"', ""]
            manifest["code_ranges"].append(region.to_dict() | {"path": path})
            cursor = region.start.offset + region.size
        if cursor < bank_end:
            main.extend(_gap(cursor, bank_end - cursor))
    manifest["assembly_bytes"] = sum(r.size for r in regions)
    manifest["base_bytes"] = len(data) - manifest["assembly_bytes"]
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "main.asm").write_text("\n".join(main), encoding="utf-8", newline="\n")
    builder = resources.files("decompnet.rom").joinpath("export_gb_build.py").read_text(encoding="utf-8")
    (out / "build.py").write_text(builder, encoding="utf-8", newline="\n")
    (out / ".gitignore").write_text("build/\n*.gb\n*.gbc\n__pycache__/\n", encoding="utf-8", newline="\n")
    (out / "README.md").write_text(
        "# Game Boy assembly project\n\n"
        "Install the pinned assembler: `decompnet toolchain install rgbds`.\n\n"
        "Build with `python build.py /path/to/your/original.gb` (or `.gbc`).\n"
        "Without decompnet installed, add `--rgbds /path/to/rgbds-1.0.4`.\n\n"
        "Edit the RGBDS assembly in `src/`. Keep each section's bank, address and size.\n"
        "The original ROM is not included. Header bytes, checksums and unknown code/data\n"
        "are included from your own base at build time. `rgbfix` is deliberately not run.\n"
        "The builder verifies the input SHA-256 and every output byte before publishing\n"
        "a ROM in `build/`. Any mismatch fails the build.\n\n"
        f"Assembly: {manifest['assembly_bytes']} bytes; base ROM: {manifest['base_bytes']} bytes.\n"
        "This is disassembly coverage, not C/C++ recovery or a completed decompilation.\n"
        "Static discovery needs review, especially bank switches, jump tables and code\n"
        "copied to RAM. See `manifest.json` for the discovered ranges and open notes.\n",
        encoding="utf-8", newline="\n")
    return manifest


def _gap(offset: int, size: int) -> list[str]:
    address = gb.Address.from_offset(offset)
    section = (f"ROMX[${address.cpu:04x}], BANK[${address.bank:x}]" if address.bank else
               f"ROM0[${address.cpu:04x}]")
    return [f'SECTION "base_{offset:06x}", {section}',
            f'INCBIN "baserom.gb", ${offset:x}, ${size:x}', ""]
