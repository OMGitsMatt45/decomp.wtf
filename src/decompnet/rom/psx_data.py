"""Reviewed boot-file data envelopes and canonical module analysis mirrors."""

import hashlib
import re
import struct

from .errors import RomError


MAX_RANGES = 128


def reviewed(disc, main, declarations):
    """Validate explicit loaded-file data, independently of its instruction shapes."""
    from .psx_layout import number
    if not isinstance(declarations, list) or len(declarations) > MAX_RANGES:
        raise RomError("reviewed PS1 main data must be a bounded list of at most 128 ranges")
    if not declarations:
        return []
    header = disc.read(main["lba"], 0x800)
    if len(header) != 0x800 or not header.startswith(b"PS-X EXE"):
        raise RomError("reviewed PS1 main data requires the original executable header")
    loaded_end = min(main["size"], 0x800 + int.from_bytes(header[0x1C:0x20], "little"))
    entry = 0x800 + int.from_bytes(header[0x10:0x14], "little") - int.from_bytes(header[0x18:0x1C], "little")
    result = []
    for item in declarations:
        if not isinstance(item, dict) or set(item) != {"offset", "size", "sha256"}:
            raise RomError("reviewed PS1 main data needs offset, size and SHA-256")
        offset, size = number(item["offset"], "main data offset"), number(item["size"], "main data size")
        sha = item["sha256"]
        if not 0x800 <= offset < offset + size <= loaded_end or offset % 4 or size % 4 or \
                not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise RomError("reviewed PS1 main data must be aligned inside the loaded boot payload with its SHA-256")
        data = disc.read(main["lba"] + offset // 2048, offset % 2048 + size)[offset % 2048:]
        if hashlib.sha256(data).hexdigest() != sha:
            raise RomError("reviewed PS1 main data differs from its original SHA-256")
        if offset <= entry < offset + size:
            raise RomError("the original PS1 boot entry cannot be classified as data")
        result.append({"offset": offset, "size": size, "sha256": sha})
    result.sort(key=lambda item: item["offset"])
    if any(a["offset"] + a["size"] > b["offset"] for a, b in zip(result, result[1:])):
        raise RomError("reviewed PS1 main data ranges overlap")
    return result


def contains(ranges, offset, size):
    return any(item["offset"] <= offset < offset + size <= item["offset"] + item["size"] for item in ranges)


def merge_facts(default, extra):
    """Data classifications add to established GP/BSS facts, without replacing them."""
    result = {name: dict(facts) for name, facts in default.items()}
    for name, facts in (extra or {}).items():
        result[name] = {**result.get(name, {}), **facts}
    return result


def synchronize(baseline, rebuilt, layout):
    """Canonical source modules own every declared mirror inside boot data."""
    if len(baseline) != len(rebuilt):
        raise RomError("PS1 analysis mirror synchronization requires unchanged image size")
    result = bytearray(rebuilt)
    for mapping in layout["maps"]:
        source = mapping["analysis_offset"]
        if not 0 <= source < source + mapping["size"] <= len(result):
            raise RomError("a PS1 canonical module exceeds its analysis image")
        desired = rebuilt[source:source + mapping["size"]]
        for copy in mapping.get("copies", []):
            if not copy.get("main_data"):
                continue
            at = copy["analysis_offset"]
            size = mapping["size"]
            if not 0 <= at < at + size <= len(result):
                raise RomError("a PS1 boot-data mirror exceeds its analysis image")
            if rebuilt[at:at + size] not in (baseline[at:at + size], desired):
                raise RomError("a PS1 boot-data mirror conflicts with its canonical source module")
            result[at:at + size] = desired
    return bytes(result)


def verify_mirrors(image, layout):
    for mapping in layout["maps"]:
        source = mapping["analysis_offset"]
        if not 0 <= source < source + mapping["size"] <= len(image):
            raise RomError("a PS1 canonical module exceeds its analysis image")
        expected = image[source:source + mapping["size"]]
        for copy in mapping.get("copies", []):
            if copy.get("main_data"):
                at = copy["analysis_offset"]
                if not 0 <= at < at + mapping["size"] <= len(image) or image[at:at + mapping["size"]] != expected:
                    raise RomError("PS1 boot-data mirrors differ from their canonical source module")


def classify(cfg, definitions):
    """Split existing code/data subsegments at reviewed main-file data edges."""
    if not definitions:
        return
    raw = cfg["segments"]
    main = next((seg for seg in raw if isinstance(seg, dict) and seg.get("name") == "main" and seg.get("type") == "code"), None)
    if main is None:
        raise RomError("reviewed PS1 main data needs the boot code segment")
    index = raw.index(main)
    end = next((seg[0] if isinstance(seg, list) else seg["start"] for seg in raw[index + 1:]
                if isinstance(seg, list) or "start" in seg), None)
    if end is None or any(not main["start"] <= item["offset"] < item["offset"] + item["size"] <= end for item in definitions):
        raise RomError("reviewed PS1 main data is outside its boot analysis segment")
    subs = main.get("subsegments") or [[main["start"], "c", "main"]]
    ordinary = [sub for sub in subs if isinstance(sub, list)]
    output = []
    for index, sub in enumerate(ordinary):
        lo, hi = sub[0], ordinary[index + 1][0] if index + 1 < len(ordinary) else end
        boundaries = sorted({lo, hi, *(edge for item in definitions for edge in (item["offset"], item["offset"] + item["size"]) if lo < edge < hi)})
        for start, stop in zip(boundaries, boundaries[1:]):
            if contains(definitions, start, stop - start):
                output.append([start, "data", f"main_reviewed_data_{start:X}"])
            elif start == lo:
                output.append(list(sub))
            else:
                output.append([start, sub[1], f"{sub[2] if len(sub) > 2 else 'main'}_after_{start:X}"])
    main["subsegments"] = output + [sub for sub in subs if not isinstance(sub, list)]


def direct_targets(code, address):
    """Original direct jumps and CPU/coprocessor branch destinations."""
    for index, (word,) in enumerate(struct.iter_unpack("<I", code)):
        pc, opcode = address + index * 4, word >> 26
        if opcode in (2, 3):
            yield ((pc + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
        elif opcode in (1, 4, 5, 6, 7) or opcode in (16, 17, 18) and word >> 21 & 31 == 8:
            value = word & 0xFFFF
            yield pc + 4 + 4 * (value - 0x10000 if value & 0x8000 else value)


def reject_control_code(code, address, definitions, load):
    if any(contains(definitions, target - load + 0x800, 4) for target in direct_targets(code, address)):
        raise RomError("executable PS1 control flow enters reviewed main data; review its classification")


def reject_control_entries(functions, definitions, load):
    """Data address formation is allowed; no executable module may enter it."""
    if not definitions:
        return
    for function in functions:
        code = b"".join(line.word.to_bytes(4, "little") for line in function.lines)
        reject_control_code(code, function.vram, definitions, load)
