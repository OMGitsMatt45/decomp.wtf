"""Exact PS1 disc reconstruction from independently rebuilt program/overlay bytes.

File extents never move. Sector headers, EDC/ECC, XA metadata, subcode, audio,
padding and unrelated files are retained from the owner's pinned image. This is
a matching build: changed payloads require a separate disc-authoring workflow.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from .n64 import RomError
from .psx import _Disc


def digest(src) -> tuple[int, str]:
    if isinstance(src, (bytes, bytearray, memoryview)):
        return len(src), hashlib.sha256(src).hexdigest()
    position = src.tell()
    src.seek(0)
    sha, size = hashlib.sha256(), 0
    while block := src.read(1 << 20):
        sha.update(block)
        size += len(block)
    src.seek(position)
    return size, sha.hexdigest()


def inventory(disc: _Disc, image_size: int) -> list[dict]:
    pvd = disc.sector(16)
    if pvd[:7] != b"\x01CD001\x01":
        raise RomError("full-disc rebuilding requires an ISO 9660 primary volume descriptor")
    root = pvd[156:190]
    if len(root) != 34 or root[0] != 34:
        raise RomError("the disc's root directory record is damaged")
    seen, entries, occupied = set(), [], []

    def walk(lba, length, path="", depth=0):
        if lba in seen or depth >= 64 or len(seen) >= 4096:
            raise RomError("the disc directory tree contains a cycle or exceeds supported limits")
        seen.add(lba)
        occupied.append((lba, lba + (length + 2047) // 2048, path or "/"))
        for rec in disc.records(lba, length):
            name = rec["path"]
            if name in (".", "..") or any(c in name for c in ("/", "\\", "\ufffd")):
                raise RomError("the disc has an unsupported ISO filename")
            rec["path"] = path + name
            if rec["extended_attributes"] or rec["unit"] or rec["gap"] or rec["flags"] & 0x80 or rec["volume"] != 1:
                raise RomError(f"{rec['path']}: extended-attribute, interleaved, multi-extent or multi-volume ISO files are unsupported")
            end = rec["lba"] + (rec["size"] + 2047) // 2048
            if end * disc.size > image_size:
                raise RomError(f"{rec['path']}: file extent is outside the disc image")
            entries.append(rec)
            if len(entries) > 100000:
                raise RomError("the disc exceeds the supported 100000 directory entries")
            if rec["directory"]:
                walk(rec["lba"], rec["size"], rec["path"] + "/", depth + 1)
            elif rec["size"]:
                occupied.append((rec["lba"], end, rec["path"]))

    walk(int.from_bytes(root[2:6], "little"), int.from_bytes(root[10:14], "little"))
    paths = [rec["path"] for rec in entries]
    if len(set(paths)) != len(paths):
        raise RomError("the disc has ambiguous duplicate ISO filenames or file versions")
    occupied.sort()
    for left, right in zip(occupied, occupied[1:]):
        if left[1] > right[0]:
            raise RomError(f"overlapping disc extents: {left[2]} and {right[2]}")
    return entries


def describe(src, boot: str, program: bytes, found: list, sources: dict) -> dict:
    size, sha = digest(src)
    layout = {"format": 1, "original_size": size, "sha256": sha}
    try:
        disc = _Disc(src)
        if size % disc.size:
            raise RomError("the disc image ends in a partial sector")
        files = inventory(disc, size)
        by_path = {f["path"]: f for f in files if not f["directory"]}
        boot = boot.upper().replace("\\", "/").strip("/").split(";", 1)[0]
        maps = []
        for segment, path, data, load, code_at in [("main", boot, program, None, 0)] + [
                ("ovl_" + name, sources[name], data, load, code_at) for name, data, load, code_at in found]:
            rec = by_path.get(path)
            if rec is None or len(data) > rec["size"] or disc.read(rec["lba"], len(data)) != data:
                raise RomError(f"{path}: discovered program bytes disagree with the disc file extent")
            # A rebuilt file must occupy ordinary 2048-byte data sectors.
            # Other sectors are retained verbatim and are never interpreted.
            if disc.size != 2048:
                for lba in range(rec["lba"], rec["lba"] + (len(data) + 2047) // 2048):
                    head = disc._get(lba * disc.size, 24)
                    if head[:12] != b"\0" + b"\xff" * 10 + b"\0":
                        raise RomError(f"{path}: invalid raw data-sector sync")
                    if disc.skip == 16 and head[15] != 1 or disc.skip == 24 and (
                            head[15] != 2 or head[16:20] != head[20:24] or head[18] & 0x20):
                        raise RomError(f"{path}: expected Mode 1 or Mode 2 Form 1 data sectors")
            maps.append({"segment": segment, "path": path, "lba": rec["lba"], "file_size": rec["size"],
                         "size": len(data), "load": load, "code_at": code_at,
                         "address_basis": "PS-X EXE header" if data.startswith(b"PS-X EXE") else "inferred absolute JAL targets",
                         "sha256": hashlib.sha256(data).hexdigest()})
        layout.update(supported=True, sector_size=disc.size, skip=disc.skip, files=files, maps=maps)
    except (RomError, KeyError) as error:
        layout.update(supported=False, reason=str(error))
    return layout


def bind(layout: dict, segments: list[dict], image: bytes) -> dict:
    """Record where splat's analysis image stores each original disc program."""
    layout = {**layout, "maps": [dict(m) for m in layout["maps"]]}
    for m in layout["maps"]:
        if m["segment"] == "main":
            offset = 0
        else:
            seg = next((s for s in segments if s["name"] == m["segment"]), None)
            if seg is None or seg["vram"] != m["load"]:
                raise RomError(f"{m['path']}: overlay load address disagrees with its discovered disc layout")
            offset = seg["rom_start"]
        if hashlib.sha256(image[offset:offset + m["size"]]).hexdigest() != m["sha256"]:
            raise RomError(f"{m['path']}: analysis bytes disagree with the original disc")
        m["analysis_offset"] = offset
    layout.update(analysis_size=len(image), analysis_sha256=hashlib.sha256(image).hexdigest())
    return layout


def verify(src, layout: dict) -> _Disc:
    if layout.get("format") != 1 or not layout.get("supported"):
        raise RomError("unsupported PS1 disc reconstruction manifest")
    if not 0 < layout["analysis_size"] <= 512 << 20:
        raise RomError("the PS1 analysis image exceeds the supported 512 MiB limit")
    size, sha = digest(src)
    if (size, sha) != (layout["original_size"], layout["sha256"]):
        raise RomError("the original PS1 disc differs (size or SHA-256)")
    disc = _Disc(src)
    if (disc.size, disc.skip) != (layout["sector_size"], layout["skip"]) or inventory(disc, size) != layout["files"]:
        raise RomError("the PS1 disc filesystem differs from the reconstruction manifest")
    by_path = {f["path"]: f for f in layout["files"] if not f["directory"]}
    ranges, storage_ranges, fields, copy_count = [], [], [], 0
    for m in layout["maps"]:
        rec = by_path.get(m["path"])
        offset, stored = m.get("file_offset", 0), m.get("stored_size", m["size"])
        if not rec or (rec["lba"], rec["size"]) != (m["lba"], m["file_size"]) or not 0 <= offset < offset + stored <= rec["size"]:
            raise RomError("a PS1 program's disc extent differs from the manifest")
        start = m["analysis_offset"]
        if start < 0 or start + m["size"] > layout["analysis_size"]:
            raise RomError("a PS1 program's analysis extent is out of bounds")
        ranges.append((start, start + m["size"]))
        capacity = m.get("storage", {}).get("capacity", stored)
        if not stored <= capacity <= rec["size"] - offset:
            raise RomError("a PS1 program's storage capacity exceeds its file bounds")
        storage_ranges.append((m["path"], offset, offset + capacity))
        copies = m.get("copies", [])
        from .psx_layout import MAX_COPIES, read_map, storage_maps, storage_layout
        if m.get("storage"):
            storage = storage_layout(disc, m, m["storage"])
            at, width = storage["length_offset"], storage["length_width"]
            fields.append((m["path"], at, at + width))
        if not isinstance(copies, list) or len(copies) > MAX_COPIES - copy_count or copies and (
                m.get("codec", "raw") != "raw" or m.get("storage")):
            raise RomError("PS1 module copies require bounded raw storage ranges")
        if copies:
            canonical = read_map(disc, m)
        for copy in copies:
            if not isinstance(copy, dict) or set(copy) != {"path", "lba", "file_size", "file_offset", "stored_size", "stored_sha256"}:
                raise RomError("a PS1 module copy has unsupported storage fields")
            copy_file, at = by_path.get(copy["path"]), copy["file_offset"]
            if not copy_file or copy["path"] == layout["maps"][0]["path"] or \
                    (copy_file["lba"], copy_file["size"]) != (copy["lba"], copy["file_size"]) or \
                    copy["stored_size"] != stored or copy["stored_sha256"] != m.get("stored_sha256") or \
                    not 0 <= at < at + stored <= copy_file["size"]:
                raise RomError("a PS1 module copy's disc extent differs from the manifest")
            storage_ranges.append((copy["path"], at, at + stored))
            copy_count += 1
        for copy_map in list(storage_maps(m))[1:]:
            if read_map(disc, copy_map) != canonical:
                raise RomError("a PS1 module copy differs from its canonical decoded bytes")
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise RomError("PS1 analysis program extents overlap")
    storage_ranges.sort()
    if any(a[0] == b[0] and a[2] > b[1] for a, b in zip(storage_ranges, storage_ranges[1:])):
        raise RomError("PS1 program storage or module copy extents overlap")
    for index, (path, start, end) in enumerate(fields):
        if any(p == path and a < end and start < b for p, a, b in storage_ranges + fields[:index]):
            raise RomError("PS1 archive length fields overlap program storage or module copies")
    return disc


def analysis(original: Path, layout: dict) -> bytes:
    """Regenerate the private joined analysis image from the owner's disc."""
    if "media" in layout:
        from . import psx_media
        psx_media.verify_files(original, layout)
        with psx_media.decoded(original, layout["media"]) as source:
            return _analysis(source, psx_media.unpack(layout))
    with original.open("rb") as src:
        return _analysis(src, layout)


def _analysis(src, layout):
    disc = verify(src, layout)
    out = bytearray(layout["analysis_size"])
    for m in layout["maps"]:
        from .psx_layout import read_map
        data = read_map(disc, m)
        if hashlib.sha256(data).hexdigest() != m["sha256"]:
            raise RomError(f"{m['path']}: original program SHA-256 differs")
        out[m["analysis_offset"]:m["analysis_offset"] + m["size"]] = data
    if hashlib.sha256(out).hexdigest() != layout["analysis_sha256"]:
        raise RomError("the regenerated PS1 analysis image differs")
    return bytes(out)


def rebuild(original: Path, rebuilt: bytes, layout: dict, output: Path) -> None:
    """Patch source-built file extents into a streamed copy; publish only exact output."""
    original, output = Path(original), Path(output)
    if original.resolve() == output.resolve():
        raise RomError("a rebuilt disc must use a separate output path")
    output.unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".psx-match-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        if len(rebuilt) != layout["analysis_size"] or hashlib.sha256(rebuilt).hexdigest() != layout["analysis_sha256"]:
            raise RomError("the source-built PS1 analysis image differs")
        if "media" in layout or layout.get("retained_modules"):
            if analysis(original, layout) != rebuilt:
                raise RomError("the source-built PS1 programs differ from the media container")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, temporary)
            with temporary.open("rb") as copied:
                if digest(copied) != (layout["original_size"], layout["sha256"]):
                    raise RomError("the retained PS1 media container differs")
            temporary.replace(output)
            return
        with original.open("rb") as src:
            disc = verify(src, layout)
            output.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w+b") as dest:
                src.seek(0)
                shutil.copyfileobj(src, dest, 1 << 20)
                for m in layout["maps"]:
                    data = rebuilt[m["analysis_offset"]:m["analysis_offset"] + m["size"]]
                    if hashlib.sha256(data).hexdigest() != m["sha256"]:
                        raise RomError(f"{m['path']}: source-built program differs")
                    for offset in range(0, len(data), 2048):
                        dest.seek((m["lba"] + offset // 2048) * disc.size + disc.skip)
                        dest.write(data[offset:offset + 2048])
                if digest(dest) != (layout["original_size"], layout["sha256"]):
                    raise RomError("the source-built full PS1 disc differs")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
