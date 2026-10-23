"""Reviewed N64 runtime layouts and reproducible private decompression views.

Addresses supplied here are facts reviewed by the project owner. Heuristic
placement remains a separate import path; unknown addresses are never filled in.
"""

import hashlib
import re
import zlib
from collections import defaultdict, deque

MAX_DECODED = 32 * 1024 * 1024
MAX_WORKING = 256 * 1024 * 1024


def number(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value, 0) if isinstance(value, str) else int(value) if isinstance(value, int) else None
    except ValueError:
        raise ValueError(f"{field} must be an integer") from None


def decode(original, block, native_blocks=None, *, verify=True):
    codec, start = block["codec"], block["offset"]
    if codec == "native":
        if native_blocks is None:
            from .n64code import unpack_code
            native_blocks = dict(unpack_code(original))
        try:
            data = native_blocks[start]
        except KeyError:
            raise ValueError("the original compressed N64 block could not be decoded") from None
    else:
        raw = original[start:block["end"]]
        expected = block["size"]
        if not 0 < expected <= MAX_DECODED:
            raise ValueError("N64 decoded module exceeds its bounded size")
        if codec == "yaz0":
            if len(raw) < 16 or raw[:4] != b"Yaz0" or int.from_bytes(raw[4:8], "big") != expected:
                raise ValueError("Yaz0 header differs from the reviewed module size")
            from .n64code import yaz0
            data = yaz0(raw)
        elif codec in ("deflate-1172", "deflate-1173", "gzip"):
            prefix = bytes.fromhex("1172" if codec.endswith("1172") else "1173")
            header = 0 if codec == "gzip" else 2 if codec.endswith("1172") else 5
            prefix = b"\x1f\x8b" if codec == "gzip" else prefix
            if len(raw) <= header or raw[:2] != prefix or \
                    (header == 5 and int.from_bytes(raw[2:5], "big") != expected):
                raise ValueError("Rare compression header differs from the reviewed module")
            stream = zlib.decompressobj(31 if codec == "gzip" else -15)
            try:
                data = stream.decompress(raw[header:], expected + 1)
            except zlib.error as error:
                raise ValueError(f"invalid N64 deflate stream: {error}") from error
            if not stream.eof or len(data) != expected:
                raise ValueError("N64 deflate stream is truncated or exceeds its reviewed size")
        else:
            raise ValueError("unsupported N64 compression codec")
    if len(data) != block["size"] or (verify and hashlib.sha256(data).hexdigest() != block["sha256"]):
        raise ValueError("decoded N64 module differs from its recorded reference")
    return data


def working_image(original, provenance):
    if len(original) != provenance["original_size"] or hashlib.sha256(original).hexdigest() != provenance["sha256"]:
        raise ValueError("the N64 cartridge differs from the reviewed original")
    result = bytearray(original)
    native = None
    if any(block["codec"] == "native" for block in provenance["blocks"]):
        from .n64code import unpack_code
        native = dict(unpack_code(original))
    for block in provenance["blocks"]:
        if not len(result) <= block["working_start"] <= len(result) + 0x2010 or \
                not 0 < block["size"] <= MAX_DECODED or block["working_start"] + block["size"] > MAX_WORKING:
            raise ValueError("invalid N64 analysis block placement")
        result += bytes(block["working_start"] - len(result))
        result += decode(original, block, native)
    result += bytes(-len(result) % 16) if provenance["blocks"] else b""
    if hashlib.sha256(result).hexdigest() != provenance["working_sha256"]:
        raise ValueError("N64 analysis image differs from its recorded layout")
    return bytes(result)


def provenance(original, blocks, image):
    return {"format": 1, "sha256": hashlib.sha256(original).hexdigest(), "original_size": len(original),
            "working_sha256": hashlib.sha256(image).hexdigest(), "blocks": blocks}


def encode(data, codec):
    """Deterministic encoders for reviewed, fixed-allocation cartridge modules."""
    data = bytes(data)
    if not 0 < len(data) <= MAX_DECODED:
        raise ValueError("N64 encoded module exceeds its bounded decoded size")
    if codec in ("deflate-1172", "deflate-1173", "gzip"):
        if codec.endswith("1173") and len(data) > 0xFFFFFF:
            raise ValueError("Rare 1173 modules have a 24-bit decoded size")
        compressor = zlib.compressobj(9, zlib.DEFLATED, 31 if codec == "gzip" else -15)
        prefix = b"" if codec == "gzip" else b"\x11\x72" if codec.endswith("1172") else b"\x11\x73" + len(data).to_bytes(3, "big")
        return prefix + compressor.compress(data) + compressor.flush()
    if codec != "yaz0":
        raise ValueError("edited automatic compressed pages need an explicit reviewed Yaz0/Rare module layout")
    output = bytearray(b"Yaz0" + len(data).to_bytes(4, "big") + bytes(8))
    positions = defaultdict(deque)
    at = 0
    while at < len(data):
        control, tokens = 0, bytearray()
        for bit in range(7, -1, -1):
            if at >= len(data):
                break
            key = data[at:at + 3]
            matches = positions[key]
            while matches and matches[0] < at - 0x1000:
                matches.popleft()
            size, distance = 0, 0
            if len(key) == 3:
                for previous in list(matches)[-64:][::-1]:
                    length, limit = 3, min(273, len(data) - at)
                    while length < limit and data[previous + length] == data[at + length]:
                        length += 1
                    if length > size:
                        size, distance = length, at - previous - 1
                    if size == limit:
                        break
            if size >= 3:
                if size >= 18:
                    tokens.extend((distance >> 8, distance & 255, size - 18))
                else:
                    tokens.extend(((size - 2) << 4 | distance >> 8, distance & 255))
            else:
                control |= 1 << bit
                tokens.append(data[at])
                size = 1
            for index in range(at, at + size):
                expired = index - 0x1000
                if expired >= 0:
                    old_key = data[expired:expired + 3]
                    old = positions.get(old_key)
                    if old and old[0] == expired:
                        old.popleft()
                        if not old:
                            del positions[old_key]
                bucket = positions[data[index:index + 3]]
                bucket.append(index)
                while bucket and bucket[0] < index - 0x1000:
                    bucket.popleft()
            at += size
        output.append(control)
        output.extend(tokens)
    return bytes(output)


def repack(original, metadata, rebuilt):
    """Recompress changed reviewed views, preserving fixed cartridge allocations."""
    reference = working_image(original, metadata)
    if len(rebuilt) != len(reference):
        raise ValueError("a modified N64 analysis image changed its pinned extents")
    result, records = bytearray(rebuilt[:len(original)]), []
    for block in metadata["blocks"]:
        start, size = block["working_start"], block["size"]
        data = rebuilt[start:start + size]
        if data == reference[start:start + size]:
            continue
        stored = encode(data, block["codec"])
        lo, hi = block["offset"], block["end"]
        if result[lo:hi] != original[lo:hi]:
            raise ValueError("edit decoded modules, not the original stored compressed streams")
        if len(stored) > hi - lo:
            raise ValueError(f"compressed module at 0x{lo:X} exceeds its reviewed storage reserve by {len(stored) - (hi - lo)} bytes")
        result[lo:lo + len(stored)] = stored
        expected = {**block, "sha256": hashlib.sha256(data).hexdigest()}
        if decode(bytes(result), expected) != data:
            raise ValueError("the recompressed N64 module failed its decoding check")
        records.append({"offset": lo, "codec": block["codec"], "stored_size": len(stored),
                        "capacity": hi - lo, "decoded_sha256": expected["sha256"]})
    return bytes(result), records


def reviewed(original, document):
    """Return a complete splat segment map, working image and container provenance."""
    if not isinstance(document, dict) or set(document) - {"format", "sha256", "modules"} or type(document.get("format")) is not int or document["format"] != 1:
        raise ValueError("N64 layout needs format 1, sha256 and a modules list")
    if document.get("sha256") != hashlib.sha256(original).hexdigest():
        raise ValueError("N64 layout SHA-256 differs from the normalized cartridge")
    modules = document.get("modules")
    if not isinstance(modules, list) or not 1 <= len(modules) <= 256:
        raise ValueError("N64 layout needs between 1 and 256 reviewed modules")
    work, records, mapped, intervals, names = bytearray(original), [], [], [], set()
    allowed = {"name", "rom_start", "rom_end", "vram", "compression", "decoded_size", "sections",
               "bss_size", "bss_address", "exclusive_group", "text_end"}
    for raw in modules:
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("unknown N64 module layout field")
        name = raw.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w{0,63}", name) or name in names:
            raise ValueError("N64 module names must be unique identifiers")
        names.add(name)
        start, end, address = [number(raw.get(key), key) for key in ("rom_start", "rom_end", "vram")]
        if None in (start, end, address) or not 0x1000 <= start < end <= len(original) or start % 4:
            raise ValueError("N64 module source extent is outside the cartridge or unaligned")
        if any(max(start, a) < min(end, b) for a, b in intervals):
            raise ValueError("reviewed N64 module source ranges overlap")
        intervals.append((start, end))
        codec = raw.get("compression", "none")
        data, at = original[start:end], start
        if codec != "none":
            size = number(raw.get("decoded_size"), "decoded_size")
            if size is None or not 0 < size <= MAX_DECODED:
                raise ValueError("compressed N64 modules need a bounded decoded_size")
            if len(work) + 0x2010 + size > MAX_WORKING:
                raise ValueError("N64 analysis image exceeds the 256 MiB working limit")
            # Decode once to establish the reference checksum; subsequent clean
            # rebuilds must reproduce exactly this reviewed decoding context.
            block = {"codec": codec, "offset": start, "end": end, "size": size}
            data = decode(original, block, verify=False)
            work += bytes(-len(work) % 16 + 0x2000)
            at = len(work)
            work += data
            records.append(block | {"sha256": hashlib.sha256(data).hexdigest(), "working_start": at})
        bss = number(raw.get("bss_size", 0), "bss_size")
        bss_address = number(raw.get("bss_address", address + len(data)), "bss_address") if address is not None else None
        if bss is None or bss_address is None or bss < 0 or len(data) % 4 or address % 4 or \
                not 0 <= address < address + len(data) <= bss_address <= bss_address + bss <= 0x100000000:
            raise ValueError("invalid N64 runtime code/data/BSS extent")
        group = raw.get("exclusive_group")
        if group is not None and (not isinstance(group, str) or not re.fullmatch(r"[A-Za-z_]\w{0,63}", group)):
            raise ValueError("N64 exclusive_group must be an identifier")
        sections = raw.get("sections", [{"offset": 0, "type": "code"}])
        if not isinstance(sections, list) or not 1 <= len(sections) <= 256:
            raise ValueError("invalid N64 module sections")
        subs, previous = [], -1
        for section in sections:
            if not isinstance(section, dict) or set(section) != {"offset", "type"}:
                raise ValueError("N64 sections need offset and type")
            offset, kind = number(section["offset"], "section offset"), section["type"]
            if offset is None or not previous < offset < len(data) or offset % 4 or kind not in ("code", "data", "rodata"):
                raise ValueError("N64 sections must be aligned, ordered and inside initialized data")
            subs.append([at + offset, "c" if kind == "code" else kind, name if kind == "code" else f"{name}_{kind}_{offset:X}"])
            previous = offset
        if number(sections[0]["offset"], "section offset") != 0 or not any(s["type"] == "code" for s in sections):
            raise ValueError("N64 sections must cover the module from zero and include code")
        if "text_end" in raw:
            text_end = number(raw["text_end"], "text_end")
            boundary = number(sections[1]["offset"], "section offset") if len(sections) > 1 else len(data)
            if sections[0]["type"] != "code" or sum(s["type"] == "code" for s in sections) != 1 or \
                    text_end is None or not 0 < text_end <= boundary or text_end % 4 or data[text_end:boundary].strip(b"\0"):
                raise ValueError("text_end must mark a reviewed zero reserve after a single text section")
        if bss:
            subs.append({"type": "bss", "name": name, "vram": bss_address})
        seg = {"name": name, "type": "code", "start": at, "vram": address, "subsegments": subs,
               "bss_size": bss_address + bss - address - len(data)}
        if group:
            seg.update(exclusive_ram_id="n64_" + group, symbol_name_format="$SEG_$VRAM", symbol_name_format_no_rom="$SEG_$VRAM")
        for other, lo, hi, other_group in mapped:
            if max(address, lo) < min(bss_address + bss, hi) and (not group or group != other_group):
                raise ValueError("overlapping N64 runtime modules need the same explicit exclusive_group")
        mapped.append((seg, address, bss_address + bss, group))
    if records:
        work += bytes(-len(work) % 16)
    segments = [{"name": "header", "type": "header", "start": 0}]
    cursor = 0x40
    for seg, *_ in sorted(mapped, key=lambda item: item[0]["start"]):
        at = seg["start"]
        size = next((r["size"] for r in records if r["working_start"] == at),
                    next((b - a for a, b in intervals if a == at), 0))
        if at > cursor:
            segments.append({"name": f"raw_{cursor:X}", "type": "bin", "start": cursor})
        segments.append(seg)
        cursor = at + size
    if cursor < len(work):
        segments.append({"name": f"raw_{cursor:X}", "type": "bin", "start": cursor})
    segments.append([len(work)])
    return segments, bytes(work), provenance(original, records, work)
