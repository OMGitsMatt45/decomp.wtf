"""CPU-scoped source units for ARM7 programs, copied blocks and overlays."""

import json
import re
import subprocess
from pathlib import Path

import yaml

from ..rom.arm7_analysis import discover
from ..rom.nds_modules import NdsImage
from ..rom.dsprot import detect
from ..elfobj import extract_function


def read_data(root, version, what, length=64, preferred=None):
    """Read ARM7 data before assigning it to a source unit, using runtime module bounds."""
    path = root / "config" / version / "arm7" / "units.json"
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    selected = None
    if "@" in what:
        selected, what = what.split("@", 1)
        if selected not in manifest["modules"]:
            return None
    info = manifest["symbols"].get(what) if what.startswith("arm7_") else None
    if info:
        address = info["address"]
    elif selected or preferred:
        try:
            address = int(what, 0)
        except ValueError:
            return None
    else:
        return None
    candidates = []
    for name, module in manifest["modules"].items():
        if selected and name != selected:
            continue
        bss = module.get("bss_address", module["address"] + module["size"])
        if module["address"] <= address < module["address"] + module["size"]:
            candidates.append((name, module, False))
        elif bss <= address < bss + module["bss_size"]:
            candidates.append((name, module, True))
    own = [c for c in candidates if c[0] == preferred]
    candidates = own or candidates
    if len(candidates) != 1:
        raise ValueError("ARM7 data address is outside a recorded module or is ambiguous; use module@0xADDRESS")
    name, module, bss = candidates[0]
    heading = f"ARM7 {name} at 0x{address:08X}"
    if bss:
        return heading + ": uninitialized BSS; no stored ROM bytes."
    binary = (root / module["binary"]).resolve()
    if root.resolve() not in binary.parents:
        raise ValueError("ARM7 reference binary is outside the project")
    offset = module["source_offset"] + address - module["address"]
    count = min(max(4, int(length or 64)), 512, module["address"] + module["size"] - address)
    with binary.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(count)
    if len(data) != count:
        raise ValueError("truncated ARM7 reference binary")
    lines = [heading + f" ({count} bytes)"]
    for at in range(0, count, 16):
        raw = data[at:at + 16]
        lines.append(f"  +0x{at:03X}: {raw.hex(' '):<47}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in raw)}")
    return "\n".join(lines)


def configure(root, version, source, data="", language=""):
    """Assign unclaimed original data/BSS to an ARM7 unit; never alter its code extent."""
    from .. import cpp
    from .ds_template.tools.arm7_build import original_region, regions

    path = root / "config" / version / "arm7" / "units.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    unit = next((u for u in manifest["units"] if u["source"] == source), None)
    if unit is None:
        raise ValueError("choose an ARM7 source file listed in this project's units")
    if language not in ("", "c", "c++"):
        raise ValueError("language must be c or c++")
    selected = {r["section"]: r for r in regions(unit)}
    module = manifest["modules"][unit["module"]]
    original = (root / module["binary"]).read_bytes()
    for field in data.split():
        parts = field.split(":")
        if len(parts) not in (3, 4) or parts[0] not in (".data", ".rodata", ".bss"):
            raise ValueError("data uses .data:address:size[:symbol], .rodata:address:size[:symbol] or .bss:address:size[:symbol]")
        section, address, size = parts[:3]
        region = {"section": section, "address": int(address, 0), "size": int(size, 0),
                  "kind": {".data": "data", ".rodata": "rodata", ".bss": "bss"}[section]}
        original_region(original, module, region)
        if len(parts) == 4:
            symbol = parts[3]
            if not re.fullmatch(r"[A-Za-z_]\w*", symbol):
                raise ValueError("invalid data symbol")
            prior = manifest["symbols"].get(symbol)
            if prior and (prior["address"] != region["address"] or prior.get("mode")):
                raise ValueError("cannot rebind an existing ARM7 symbol")
            manifest["symbols"][symbol] = {"address": region["address"]}
            region["symbol"] = symbol
        selected[section] = region
    # Includes this file's text and every other file's data, even if not linked.
    owned = [(u["source"], r) for u in manifest["units"] if u["module"] == unit["module"]
             for r in (selected.values() if u is unit else regions(u))]
    for i, (owner, region) in enumerate(owned):
        for other, candidate in owned[i + 1:]:
            if max(region["address"], candidate["address"]) < min(region["address"] + region["size"],
                                                                  candidate["address"] + candidate["size"]):
                raise ValueError(f"ARM7 section ownership overlaps {owner} and {other}")
    unit["regions"] = list(selected.values())
    destination = str(Path(source).with_suffix(".cpp" if language == "c++" else ".c")).replace("\\", "/") if language else source
    if destination != source and (root / destination).exists():
        raise ValueError("the destination source file already exists")
    markers = path.with_name("delinks.txt")
    text = markers.read_text(encoding="utf-8")
    pattern = re.compile(r"^" + re.escape(source) + r":\s*\n((?:[ \t].*(?:\n|$)|\s*\n)*)", re.M)
    match = pattern.search(text)
    if not match:
        raise ValueError("ARM7 source file has no link-state entry")
    body = re.sub(r"^[ \t]+complete\s*\n", "", match[1], flags=re.M)
    text = text[:match.start()] + destination + ":\n" + body + text[match.end():]
    unit["source"] = destination
    if destination != source:
        content = (root / source).read_text(encoding="utf-8")
        (root / destination).write_text(cpp.game_abi(content) if language == "c++" else content, encoding="utf-8")
        (root / source).unlink()
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    markers.write_text(text, encoding="utf-8")
    return destination


def prepare(root: Path, version: str, game: Path) -> int:
    image = NdsImage.read(game)
    from .. import toolchains
    from .ds_template.tools import arm7_codec
    directory = root / "config" / version / "arm7"
    directory.mkdir(parents=True, exist_ok=True)
    extracted = root / "extract" / version
    config = yaml.safe_load((extracted / "config.yaml").read_text(encoding="utf-8"))
    main_offset = int.from_bytes(image.data[0x30:0x34], "little")
    overlays = {}
    if config.get("arm7_overlays"):
        table = extracted / config["arm7_overlays"]
        # Only paths/IDs are needed here; preserve toolkit tags without constructing objects.
        document = yaml.compose(table.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        fields = lambda node: {key.value: value for key, value in node.value}
        for node in fields(document)["overlays"].value:
            item = fields(node)
            overlays[int(item["id"].value)] = (table.parent / item["file_name"].value, item)
    modules = {}
    decoded, protected_entries = {}, {}
    for name, module in image.modules.items():
        if module.cpu != "arm7":
            continue
        overlay = overlays.get(module.overlay_id)
        binary = overlay[0] if overlay else extracted / config["arm7_bin"] if module.overlay_id is None else None
        if binary is None:
            raise ValueError(f"missing extracted ARM7 overlay {module.overlay_id}")
        modules[name] = {"address": module.address, "size": module.code_size, "bss_size": module.bss_size,
                         "bss_address": module.bss_address if module.bss_address is not None else module.address + module.code_size,
                         "binary": binary.relative_to(root).as_posix(),
                         "source_offset": 0 if module.overlay_id is not None else module.offset - main_offset}
        offset = modules[name]["source_offset"]
        stored = binary.read_bytes()[offset:offset + module.code_size]
        if len(stored) != module.code_size:
            raise ValueError(f"truncated extracted ARM7 module {name}")
        if module.overlay_id is not None:
            decoded[name] = stored
            state = overlay[1].get("dsprot")
            if isinstance(state, yaml.MappingNode):
                state = yaml.load(yaml.serialize(state), Loader=yaml.BaseLoader).get("unencrypted")
                if state:
                    protected_entries[name] = arm7_codec.entries(state)
        if detect(stored, module.address) and name not in protected_entries:
            context = extracted / "arm7-context" / name.replace(":", "-")
            try:
                plain, state = arm7_codec.decode(toolchains.binary("dsd"), stored, module.address, context)
            except (ValueError, OSError, subprocess.TimeoutExpired):
                # A signature alone cannot prove either its module base or a
                # supported protection layout. Preserve it without source claims.
                decoded.pop(name, None)
                modules[name]["recovery_status"] = "retained: protection could not be decoded and re-encrypted exactly"
                continue
            plain_path = context.parent / (context.name + ".bin")
            plain_path.write_bytes(plain)
            info = modules[name]
            info.update(output_binary=info["binary"], output_offset=info["source_offset"],
                        codec=context.relative_to(root).as_posix(), source_offset=0,
                        binary=plain_path.relative_to(root).as_posix())
            decoded[name], protected_entries[name] = plain, arm7_codec.entries(state)
    functions = discover(image, decoded=decoded, protected_entries=protected_entries)
    names = {(f.module, f.address): f"arm7_{re.sub('[^A-Za-z0-9_]', '_', f.module.removeprefix('arm7').strip(':') or 'main')}_{f.address:08X}"
             for f in functions}
    symbols = {name: {"address": address, "mode": next(f.mode for f in functions
                                                      if f.module == module and f.address == address)}
               for (module, address), name in names.items()}
    for function in functions:
        module = image.modules[function.module]
        data = decoded.get(function.module)
        if data is None:
            data = image.code(function.module)
        for pool in function.pools:
            at = pool - module.address
            value = int.from_bytes(data[at:at + 4], "little")
            if 0x02000000 <= value < 0x04001000:
                symbols.setdefault(f"arm7_data_{value:08X}", {"address": value})
    units, markers = [], []
    for function in functions:
        symbol = names[function.module, function.address]
        source = f"src/auto/{symbol}.c"
        file = root / source
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f'/* ARM7 {function.module}, runtime address 0x{function.address:08X}. */\n#include "common.h"\n',
                        encoding="utf-8")
        unit = {"name": f"arm7/{function.module.removeprefix('arm7').strip(':') or 'main'}/{symbol}",
                "source": source, "symbol": symbol, "module": function.module,
                "address": function.address, "size": function.size, "mode": function.mode,
                "instructions": [i.address - function.address for i in function.instructions],
                "pools": sorted(p - function.address for p in function.pools)}
        units.append(unit)
        markers.append(f"{source}:\n    .text start:0x{function.address:08x} end:0x{function.address + function.size:08x}\n")
        visible = {f.address: names[f.module, f.address] for f in functions if f.module == function.module}
        for address, mode in function.calls:
            if address not in visible:
                candidates = [names[f.module, f.address] for f in functions if f.address == address]
                target = candidates[0] if len(candidates) == 1 else f"arm7_external_{address:08X}"
                visible[address] = target
                symbols.setdefault(target, {"address": address, "mode": mode})
        unit["call_symbols"] = {str(address): visible[address] for address, _ in function.calls}
    (directory / "units.json").write_text(json.dumps({"modules": modules, "symbols": symbols, "units": units}, indent=2),
                                         encoding="utf-8")
    (directory / "delinks.txt").write_text("\n".join(markers), encoding="utf-8")
    return len(units)


def raw_match(unit, symbol):
    original = extract_function(unit.target.read_bytes(), symbol) if unit.target and unit.target.is_file() else None
    candidate = extract_function(unit.base.read_bytes(), symbol) if unit.base and unit.base.is_file() else None
    exact = bool(original and candidate and original.arch == candidate.arch and
                 original.big_endian == candidate.big_endian and original.code == candidate.code and
                 not original.relocs and not candidate.relocs)
    return exact, original, candidate


def enforce_diff(unit, symbol, result):
    if symbol is None:
        for name, score in list(result.unit_scores.items()):
            exact, original, candidate = raw_match(unit, name)
            if exact:
                result.unit_scores[name] = 100.0
            elif original and candidate:
                result.unit_scores[name] = min(score or 0.0, 99.99)
        return result
    exact, original, candidate = raw_match(unit, symbol)
    if exact:
        result.match_percent = 100.0
        result.unit_scores[symbol] = 100.0
        result.literals = []
    elif original and candidate:
        result.match_percent = min(result.match_percent or 0.0, 99.99)
        result.unit_scores[symbol] = result.match_percent
        offset = next((i for i, (a, b) in enumerate(zip(original.code, candidate.code)) if a != b),
                      min(len(original.code), len(candidate.code)))
        result.raw_difference = (f"NOT A MATCH: linked ARM7 bytes, size or instruction mode differ at +0x{offset:X}. "
                                 "Call destinations and data addresses must match too.")
    return result


def enforce_report(units, report):
    """ARM7 progress counts raw linked bytes, including branch and literal addresses."""
    selected = {unit.name: unit for unit in units if unit.name.startswith("arm7/")}
    if not selected:
        return report
    for record in report.get("units", []):
        unit = selected.get(record["name"])
        if unit is None:
            continue
        matched = 0
        for function in record.get("functions", []):
            exact, original, candidate = raw_match(unit, function["name"])
            if exact:
                function["fuzzy_match_percent"] = 100.0
                matched += int(function.get("size", 0))
            elif candidate is not None:
                function["fuzzy_match_percent"] = min(function.get("fuzzy_match_percent") or 0.0, 99.99)
        measures = record.setdefault("measures", {})
        measures["matched_code"] = matched
        measures["matched_functions"] = sum(f.get("fuzzy_match_percent") == 100 for f in record.get("functions", []))
        measures["matched_code_percent"] = 100.0 * matched / max(1, int(measures.get("total_code", 0)))
        measures["matched_functions_percent"] = 100.0 * measures["matched_functions"] / max(1, int(measures.get("total_functions", 0)))
    measures = report.setdefault("measures", {})
    for key in ("matched_code", "matched_functions"):
        measures[key] = sum(int(u.get("measures", {}).get(key, 0)) for u in report.get("units", []))
    measures["matched_code_percent"] = 100.0 * measures["matched_code"] / max(1, int(measures.get("total_code", 0)))
    measures["matched_functions_percent"] = 100.0 * measures["matched_functions"] / max(1, int(measures.get("total_functions", 0)))
    return report
