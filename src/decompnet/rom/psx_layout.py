"""Hash-bound, reviewed archive/compressed module layouts for PS1 matching.

This declares loader facts; it does not guess proprietary archive formats.
Only the specified decoded bytes become recovery targets. Original encoded
storage is retained after all source-built modules match those targets.
"""

from contextlib import contextmanager
import hashlib
import io
import re
import zlib
from pathlib import Path

from .n64 import RomError
from .psx import _Disc


def number(value, name):
    try:
        if isinstance(value, bool):
            raise ValueError()
        if not isinstance(value, (int, str)):
            raise ValueError()
        return int(value, 0) if isinstance(value, str) else value
    except (TypeError, ValueError):
        raise RomError(name + " must be an integer or a hexadecimal string") from None


def transform(stored, mapping):
    codec = mapping.get("codec", "raw")
    if codec == "raw":
        data = stored
    elif codec in ("zlib", "gzip"):
        decoder = zlib.decompressobj(31 if codec == "gzip" else 15)
        try:
            data = decoder.decompress(stored, mapping["size"] + 1)
        except zlib.error as error:
            raise RomError("invalid compressed PS1 module: " + str(error)) from error
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise RomError("compressed PS1 module exceeds its decoded bound or has trailing data")
    else:
        raise RomError("PS1 module codec must be raw, zlib or gzip")
    if len(data) != mapping["size"]:
        raise RomError("PS1 module decoded size differs from the reviewed layout")
    data = bytearray(data)
    for relocation in mapping.get("relocations", []):
        at, kind, value = relocation["offset"], relocation["type"], relocation["value"]
        word = int.from_bytes(data[at:at + 4], "little")
        if kind == "R_MIPS_32":
            word = value
        elif kind == "R_MIPS_26":
            if word >> 26 not in (2, 3):
                raise RomError("PS1 jump relocations must refer to a J or JAL instruction")
            word = (word & 0xFC000000) | ((value >> 2) & 0x03FFFFFF)
        elif kind == "R_MIPS_HI16":
            if word >> 26 != 15:
                raise RomError("PS1 high-half relocations must refer to a LUI instruction")
            word = (word & 0xFFFF0000) | (((value + 0x8000) >> 16) & 0xFFFF)
        elif kind == "R_MIPS_LO16":
            word = (word & 0xFFFF0000) | (value & 0xFFFF)
        data[at:at + 4] = word.to_bytes(4, "little")
    return bytes(data)


def read_map(disc, mapping):
    offset = mapping.get("file_offset", 0)
    size = mapping.get("stored_size", mapping["size"])
    data = disc.read(mapping["lba"] + offset // 2048, offset % 2048 + size)[offset % 2048:]
    if "stored_sha256" in mapping and hashlib.sha256(data).hexdigest() != mapping["stored_sha256"]:
        raise RomError("PS1 archived module storage differs")
    return transform(data, mapping) if "codec" in mapping else data


def storage_layout(disc, mapping, storage):
    """An archive's loader length field and unused encoded capacity are explicit facts."""
    if not isinstance(storage, dict) or set(storage) != {"capacity", "length_offset", "length_width", "endian"}:
        raise RomError("PS1 storage needs capacity, length_offset, length_width and endian")
    capacity = number(storage["capacity"], "storage capacity")
    at, width = number(storage["length_offset"], "length_offset"), number(storage["length_width"], "length_width")
    endian = storage["endian"]
    offset, size = mapping["file_offset"], mapping["stored_size"]
    if width not in (2, 4) or endian not in ("little", "big") or not size <= capacity <= min(8 << 20, (1 << (8 * width)) - 1) or \
            not 0 <= at < at + width <= mapping["file_size"] or offset + capacity > mapping["file_size"]:
        raise RomError("PS1 archive storage or length field is outside its file bounds")
    def fragment(at, count):
        return disc.read(mapping["lba"] + at // 2048, at % 2048 + count)[at % 2048:] if count else b""
    if int.from_bytes(fragment(at, width), endian) != size:
        raise RomError("PS1 archive length field differs from its reviewed stored size")
    if fragment(offset + size, capacity - size).strip(b"\0"):
        raise RomError("additional PS1 archive storage must contain only original zero bytes")
    return {"capacity": capacity, "length_offset": at, "length_width": width, "endian": endian}


def encode_mod(disc, mapping, data, baseline):
    """Preserve original loader fixups; recompress into a reviewed archive allocation."""
    offset, size = mapping.get("file_offset", 0), mapping.get("stored_size", mapping["size"])
    stored = disc.read(mapping["lba"] + offset // 2048, offset % 2048 + size)[offset % 2048:]
    unrelocated = transform(stored, dict(mapping, relocations=[]))
    decoded = bytearray(data)
    for relocation in mapping.get("relocations", []):
        at = relocation["offset"]
        if data[at:at + 4] != baseline[at:at + 4]:
            raise RomError("changed loader relocation sites require a revised relocation-table authoring adapter")
        decoded[at:at + 4] = unrelocated[at:at + 4]
    codec = mapping.get("codec", "raw")
    if codec == "raw":
        encoded = bytes(decoded)
    else:
        if not mapping.get("storage"):
            raise RomError("changed encoded modules require a reviewed storage/loader authoring adapter")
        encoder = zlib.compressobj(9, zlib.DEFLATED, 31 if codec == "gzip" else 15)
        encoded = encoder.compress(decoded) + encoder.flush()
        if codec == "gzip":
            encoded = encoded[:9] + b"\xff" + encoded[10:]  # neutral OS byte; gzip mtime is already zero
    storage = storage_layout(disc, mapping, mapping["storage"]) if mapping.get("storage") else None
    if len(encoded) > (storage["capacity"] if storage else size):
        raise RomError("changed PS1 module exceeds its reviewed encoded storage")
    if transform(encoded, mapping) != data:
        raise RomError("encoded PS1 mod does not recover its source-built analysis bytes")
    return encoded, storage


@contextmanager
def source(src, layout):
    from .psx_media import decoded, inside
    if isinstance(src, (str, Path)):
        path = Path(src)
        media = layout.get("media")
        if media:
            if media["kind"] == "cue":
                path = inside(path.parent, media["primary"])
            with decoded(path, media) as stream:
                yield stream
        else:
            with path.open("rb") as stream:
                yield stream
    else:
        yield io.BytesIO(src)


def apply(picked, src, reviewed):
    layout = picked.disc
    if not layout or not layout.get("supported"):
        raise RomError("reviewed PS1 modules require a supported full disc image")
    if not isinstance(reviewed, dict) or set(reviewed) - {"format", "sha256", "modules"} or reviewed.get("format") != 1 or reviewed.get("sha256") != layout["sha256"]:
        raise RomError("the reviewed PS1 layout must use format 1 and the original disc SHA-256")
    definitions = reviewed.get("modules")
    if not isinstance(definitions, list) or not 1 <= len(definitions) <= 128:
        raise RomError("declare 1 to 128 reviewed PS1 modules")
    files = {f["path"]: f for f in layout["files"] if not f["directory"]}
    maps, overlays, modules, occupied = [layout["maps"][0]], [], {}, []
    allowed = {"name", "path", "offset", "stored_size", "size", "codec", "load", "code_start", "code_end", "gp", "bss", "bss_size", "relocations", "storage"}
    with source(src, layout) as stream:
        disc = _Disc(stream)
        for item in definitions:
            if not isinstance(item, dict) or set(item) - allowed or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", str(item.get("name", ""))):
                raise RomError("reviewed PS1 modules need distinct simple names and supported fields")
            name = item["name"]
            if "ovl_" + name in modules:
                raise RomError("duplicate reviewed PS1 module name")
            path = str(item.get("path", "")).upper()
            rec = files.get(path)
            if not rec or path == maps[0]["path"]:
                raise RomError("reviewed modules must name an existing non-boot ISO file")
            offset = number(item.get("offset", 0), "offset")
            stored_size = number(item.get("stored_size"), "stored_size")
            size = number(item.get("size"), "size")
            load = number(item.get("load"), "load")
            start = number(item.get("code_start", 0), "code_start")
            end = number(item.get("code_end", size), "code_end")
            gp = number(item.get("gp", 0), "gp")
            bss, bss_size = number(item.get("bss", 0), "bss"), number(item.get("bss_size", 0), "bss_size")
            if not 0 <= offset < offset + stored_size <= rec["size"] or stored_size > 8 << 20:
                raise RomError("PS1 archived module storage is out of bounds")
            if not 0 < size <= 2 << 20 or not 0x80000000 <= load < load + size <= 0x80200000 or load % 4:
                raise RomError("PS1 decoded module exceeds its RAM bounds")
            if not 0 <= start < end <= size or start % 4 or end % 4:
                raise RomError("PS1 module text offsets must be aligned inside decoded bytes")
            if gp and (not 0x80000000 <= gp < 0x80200000 or gp % 4):
                raise RomError("PS1 module GP must be aligned in RAM")
            if bss_size < 0 or bss_size and not load + size <= bss < bss + bss_size <= 0x80200000:
                raise RomError("PS1 module BSS overlaps loaded bytes or exceeds RAM")
            relocations, positions = [], set()
            raw_relocations = item.get("relocations", [])
            if not isinstance(raw_relocations, list) or len(raw_relocations) > 100000:
                raise RomError("PS1 relocations must be a bounded list")
            for relocation in raw_relocations:
                if not isinstance(relocation, dict) or set(relocation) != {"offset", "type", "value"}:
                    raise RomError("PS1 relocations require offset, type and resolved value")
                at, value = number(relocation["offset"], "relocation offset"), number(relocation["value"], "relocation value")
                kind = relocation["type"]
                if kind not in ("R_MIPS_32", "R_MIPS_26", "R_MIPS_HI16", "R_MIPS_LO16") or at % 4 or not 0 <= at <= size - 4 or at in positions or not 0 <= value <= 0xFFFFFFFF:
                    raise RomError("unsupported, duplicate or out-of-bounds PS1 relocation")
                if kind == "R_MIPS_26" and (value % 4 or value >> 28 != (load + at + 4) >> 28):
                    raise RomError("PS1 jump relocation target is unaligned or outside its MIPS region")
                positions.add(at)
                relocations.append({"offset": at, "type": kind, "value": value})
            mapping = {"segment": "ovl_" + name, "path": path, "lba": rec["lba"], "file_size": rec["size"],
                "file_offset": offset, "stored_size": stored_size, "size": size, "load": load, "code_at": start,
                "codec": item.get("codec", "raw"), "relocations": relocations,
                "address_basis": "reviewed loader layout"}
            if "storage" in item:
                mapping["storage"] = storage_layout(disc, mapping, item["storage"])
            capacity = mapping.get("storage", {}).get("capacity", stored_size)
            if any(p == path and a < offset + capacity and offset < b for p, a, b in occupied):
                raise RomError("reviewed PS1 module storage extents overlap")
            occupied.append((path, offset, offset + capacity))
            stored = disc.read(rec["lba"] + offset // 2048, offset % 2048 + stored_size)[offset % 2048:]
            mapping["stored_sha256"] = hashlib.sha256(stored).hexdigest()
            data = transform(stored, mapping)
            mapping["sha256"] = hashlib.sha256(data).hexdigest()
            maps.append(mapping)
            overlays.append((name, data, load, start))
            modules["ovl_" + name] = {"gp": gp, "bss": bss, "bss_size": bss_size,
                "code_start": start, "code_end": end, "basis": "reviewed loader layout"}
    fields = []
    for mapping in maps:
        if storage := mapping.get("storage"):
            at, width, path = storage["length_offset"], storage["length_width"], mapping["path"]
            if any(p == path and a < at + width and at < b for p, a, b in occupied + fields):
                raise RomError("PS1 archive length fields overlap module storage or another length field")
            fields.append((path, at, at + width))
    if sum(m["size"] for m in maps) > 16 << 20:
        raise RomError("reviewed PS1 programs exceed the supported 16 MiB analysis limit")
    picked.overlays = overlays
    picked.disc = dict(layout, maps=maps, retained_modules=True)
    return modules
