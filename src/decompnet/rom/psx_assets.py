"""Reviewed disc-resource replacements and HBD edits in exported PS1 projects."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import psx_disc, psx_media, psx_sector, psx_hbd, psx_layout
from .errors import RomError
from .psx import _Disc


def project(root):
    root = Path(root).resolve()
    meta = json.loads((root / "build.json").read_text(encoding="utf-8"))
    if meta.get("platform") != "psx" or not meta.get("disc"):
        raise RomError("choose an exported PS1 disc project; use discs/disc-N inside combined projects")
    return root, meta


@contextmanager
def opened(path, layout):
    media = layout.get("media")
    if media:
        with psx_media.decoded(path, media) as stream:
            yield _Disc(stream), stream
    else:
        with Path(path).open("rb") as stream:
            yield _Disc(stream), stream


def path_name(name):
    return psx_media.relative(name).upper()


def reader(disc, record):
    def read(offset, count):
        if offset < 0 or count < 0 or offset + count > record["size"]:
            raise RomError("resource read exceeds its ISO file")
        return disc.read(record["lba"] + offset // 2048, offset % 2048 + count)[offset % 2048:]
    return read


def program_storage(layout):
    for mapping in layout["maps"]:
        yield from psx_layout.storage_maps(mapping)


def load(root, meta):
    path = root / "psx-assets.json"
    declaration = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "format": 1, "sha256": meta["disc"]["layout"]["sha256"], "files": [], "archives": []}
    if not isinstance(declaration, dict) or set(declaration) != {"format", "sha256", "files", "archives"} or declaration["format"] != 1 or \
            declaration["sha256"] != meta["disc"]["layout"]["sha256"] or \
            not isinstance(declaration["files"], list) or not isinstance(declaration["archives"], list) or \
            len(declaration["files"]) + len(declaration["archives"]) > 4096:
        raise RomError("PS1 assets must use format 1 and the pinned original disc SHA-256")
    for category, fields in (("files", {"path", "source", "relocate", "references"}),
                             ("archives", {"path", "source", "sector", "member"})):
        for item in declaration[category]:
            if not isinstance(item, dict) or set(item) != fields or not isinstance(item["path"], str) or \
                    item["path"] != path_name(item["path"]) or not isinstance(item["source"], str) or \
                    not item["source"].startswith("mod-assets/"):
                raise RomError("invalid PS1 asset declaration")
            psx_media.inside(root, item["source"])
            if category == "files" and not isinstance(item["relocate"], bool) or category == "archives" and any(
                    isinstance(item[key], bool) or not isinstance(item[key], int) or item[key] < 0 for key in ("sector", "member")):
                raise RomError("invalid PS1 asset placement")
    return declaration


def _original(root, meta):
    original = psx_media.inside(root, meta["disc"]["image"])
    layout = meta["disc"]["layout"]
    # Verify the complete pinned image and program/overlay targets first.
    psx_disc.analysis(original, layout)
    return original, layout


def extract(root, name, output):
    root, meta = project(root)
    original, layout = _original(root, meta)
    name = path_name(name)
    record = next((r for r in layout["files"] if r["path"] == name and not r["directory"]), None)
    if record is None:
        raise RomError("choose an existing ISO file")
    output = Path(output)
    if output.resolve() == original.resolve() or root in output.resolve().parents:
        raise RomError("extract resources to a separate path outside the exported project")
    output.parent.mkdir(parents=True, exist_ok=True)
    with opened(original, layout) as (disc, _), tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as dest:
        temporary = Path(dest.name)
        try:
            read = reader(disc, record)
            for at in range(0, record["size"], 1 << 20):
                dest.write(read(at, min(1 << 20, record["size"] - at)))
            dest.close()
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return psx_media.record(output, output.name)


def stage(root, name, source, *, relocate=False, references=None, sector=None, member=None):
    root, meta = project(root)
    helper = root / "psx_mod.py"
    if helper.exists() and "from decompnet.rom.psx_assets import" not in helper.read_text(encoding="utf-8"):
        raise RomError("this export needs current asset build helpers; run `decompnet psx upgrade PATH` first")
    original, layout = _original(root, meta)
    name = path_name(name)
    record = next((r for r in layout["files"] if r["path"] == name and not r["directory"]), None)
    if record is None or any(m["path"] == name for m in program_storage(layout)):
        raise RomError("choose an existing resource file; mapped programs must be edited through source")
    source = Path(source)
    maximum = 16 << 20 if sector is not None else 128 << 20
    if source.stat().st_size > maximum:
        raise RomError("replacement resource exceeds its supported size bound")
    data = source.read_bytes()
    declaration = load(root, meta)
    with opened(original, layout) as (disc, _):
        if sector is not None:
            item = psx_hbd.block(reader(disc, record), record["size"], sector)
            if item is None or not isinstance(member, int) or not 0 <= member < len(item["members"]):
                raise RomError("choose an existing Heartbeat archive block and member index")
            psx_hbd.decoded(reader(disc, record), item["members"][member])
        elif len(data) > (record["size"] + 2047) // 2048 * 2048 and not relocate:
            raise RomError("resource growth requires --relocate and review of the game's file addressing")
        _references(disc, layout, record, references or [])
    identifier = hashlib.sha256((name + str(sector) + str(member)).encode()).hexdigest()[:24]
    target = psx_media.inside(root, f"mod-assets/{identifier}.bin")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.close()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    entry = {"path": name, "source": target.relative_to(root).as_posix()}
    if sector is None:
        entry.update(relocate=bool(relocate), references=references or [])
        declaration["files"] = [r for r in declaration["files"] if r["path"] != name] + [entry]
    else:
        entry.update(sector=sector, member=member)
        declaration["archives"] = [r for r in declaration["archives"] if (r["path"], r["sector"], r["member"]) != (name, sector, member)] + [entry]
    _save(root / "psx-assets.json", declaration)
    return declaration


def _save(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _references(disc, layout, resource, references):
    if not isinstance(references, list) or len(references) > 10000:
        raise RomError("resource loader references must be a bounded list")
    files = {r["path"]: r for r in layout["files"] if not r["directory"]}
    used = []
    values = {"lba": resource["lba"], "size": resource["size"], "sectors": (resource["size"] + 2047) // 2048}
    for ref in references:
        if not isinstance(ref, dict) or set(ref) != {"file", "offset", "kind", "width", "endian"}:
            raise RomError("loader references need file, offset, kind, width and endian")
        if not all(isinstance(ref[key], str) for key in ("file", "kind", "endian")):
            raise RomError("loader reference names and byte order must be strings")
        record = files.get(ref["file"])
        at, width = ref["offset"], ref["width"]
        if not record or isinstance(at, bool) or not isinstance(at, int) or width not in (2, 3, 4) or \
                ref["kind"] not in values or ref["endian"] not in ("little", "big") or not 0 <= at <= record["size"] - width:
            raise RomError("invalid or out-of-bounds resource loader reference")
        if any(p == record["path"] and lo < at + width and at < hi for p, lo, hi in used):
            raise RomError("resource loader references overlap")
        for mapping in program_storage(layout):
            start = mapping.get("file_offset", 0)
            size = mapping.get("storage", {}).get("capacity", mapping.get("stored_size", mapping["size"]))
            if mapping["path"] == record["path"] and start < at + width and at < start + size:
                raise RomError("resource loader references overlap mapped program storage; edit programs through source")
        used.append((record["path"], at, at + width))
        if int.from_bytes(reader(disc, record)(at, width), ref["endian"]) != values[ref["kind"]]:
            raise RomError("resource loader reference differs from the pinned original value")


def _records(disc):
    pvd = disc.sector(16)
    result = {}
    def walk(lba, length, prefix=""):
        for rec in disc.records(lba, length, offsets=True):
            name = prefix + rec["path"]
            result[name] = rec
            if rec["directory"]:
                walk(rec["lba"], rec["size"], name + "/")
    walk(int.from_bytes(pvd[158:162], "little"), int.from_bytes(pvd[166:170], "little"))
    return result


def _cue(root, meta):
    layout, original = meta["disc"]["layout"], root / meta["disc"]["image"]
    media = layout.get("media", {})
    if media.get("kind") != "cue":
        return None
    item = next(r for r in media["companions"] if r["name"].lower().endswith(".cue"))
    return item, psx_media.inside(original.parent / media["directory"], item["name"]).read_bytes()


def cue_shift(data, primary, frames):
    current, mode, cut, lines = None, None, None, []
    for line in data.splitlines(keepends=True):
        text = line.decode("utf-8-sig").strip()
        file = re.fullmatch(r'FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY', text, re.I)
        track = re.fullmatch(r"TRACK\s+\d+\s+(\S+)", text, re.I)
        index = re.fullmatch(r"INDEX\s+\d+\s+(\d+):(\d{2}):(\d{2})", text, re.I)
        if file:
            current = psx_media.relative(file[1] or file[2])
        elif track:
            mode = track[1].upper()
        elif index and current == primary and mode == "AUDIO":
            old = (int(index[1]) * 60 + int(index[2])) * 75 + int(index[3])
            cut = old if cut is None else min(cut, old)
            new = old + frames
            if new >= 450000:
                raise RomError("resized CUE exceeds the supported CD time range")
            replacement = f"{new // 4500:02}:{new // 75 % 60:02}:{new % 75:02}".encode()
            line = re.sub(rb"\d+:\d{2}:\d{2}(?=\s*$)", replacement, line)
        lines.append(line)
    return cut, b"".join(lines)


def _raw_sector(payload, lba, mode, size):
    if size == 2048:
        return payload
    frame = bytearray(size)
    frame[:12] = b"\0" + b"\xff" * 10 + b"\0"
    minute, rem = divmod(lba + 150, 4500)
    second, index = divmod(rem, 75)
    if minute >= 100:
        raise RomError("resized data track exceeds the supported CD time range")
    bcd = lambda value: value // 10 * 16 + value % 10
    frame[12:16] = bytes([bcd(minute), bcd(second), bcd(index), mode])
    skip = 16 if mode == 1 else 24
    if mode == 2:
        frame[16:24] = bytes([0, 0, 8, 0]) * 2
    frame[skip:skip + 2048] = payload
    return psx_sector.corrected(frame)


def _media_root(output, primary):
    root = output
    for _ in Path(primary).parts:
        root = root.parent
    return root


def _tail_hash(stream, start):
    stream.seek(start)
    sha, size = hashlib.sha256(), 0
    while data := stream.read(1 << 20):
        sha.update(data)
        size += len(data)
    return size, sha.hexdigest()


def apply(root, meta, output):
    declaration = load(root, meta)
    if not declaration["files"] and not declaration["archives"]:
        return None
    layout = meta["disc"]["layout"]
    media = layout.get("media", {})
    original = root / meta["disc"]["image"]
    files = {r["path"]: r for r in layout["files"] if not r["directory"]}
    if len({r["path"] for r in declaration["files"]}) != len(declaration["files"]):
        raise RomError("duplicate replacement resource")
    mapped = {m["path"] for m in program_storage(layout)}
    resources, archives, total = [], {}, 0
    for entry in declaration["files"] + declaration["archives"]:
        name = entry["path"]
        if name not in files or name in mapped:
            raise RomError("replacement resource is missing or overlaps a mapped program")
        source = psx_media.inside(root, entry["source"])
        maximum = 16 << 20 if "sector" in entry else 128 << 20
        total += source.stat().st_size
        if source.stat().st_size > maximum or total > 256 << 20:
            raise RomError("replacement assets exceed their size bounds")
        data = source.read_bytes()
        if "sector" in entry:
            key = name, entry["sector"]
            if name in {r["path"] for r in declaration["files"]} or entry["member"] in archives.setdefault(key, {}):
                raise RomError("whole-file and member replacements conflict or duplicate")
            archives[key][entry["member"]] = data
        else:
            resources.append((entry, data))
    cue = _cue(root, meta)
    with opened(output, layout) as (disc, stream), opened(original, layout) as (baseline, _):
        records, patches = _records(disc), {}
        stream.seek(0, 2)
        old_length = stream.tell()
        physical_offset = media.get("offset", 0)
        cut = old_length // disc.size
        if cue:
            first_audio, _ = cue_shift(cue[1], media["primary"], 0)
            if first_audio is not None:
                cut = first_audio - physical_offset // disc.size
        chd_growth = media.get("kind") == "chd" and any(
            len(data) > (files[entry["path"]]["size"] + 2047) // 2048 * 2048 for entry, data in resources)
        if chd_growth:
            from .psx_chd_tracks import tracks
            cut = tracks(stream)[0]["padded"]
        tail_size, tail_sha = _tail_hash(stream, cut * disc.size)
        next_lba, changed, references, archive_changes = cut, [], [], []
        edited_paths = {entry["path"] for entry, _ in resources} | {name for name, _ in archives}
        reference_spans = []
        for entry, _ in resources:
            _references(baseline, layout, files[entry["path"]], entry["references"])
            for ref in entry["references"]:
                if ref["file"] in edited_paths:
                    raise RomError("loader references cannot target another replaced resource or archive")
                span = ref["file"], ref["offset"], ref["offset"] + ref["width"]
                if any(p == span[0] and lo < span[2] and span[1] < hi for p, lo, hi in reference_spans):
                    raise RomError("resource loader references overlap across replacements")
                reference_spans.append(span)
        def patch(offset, data):
            at = 0
            while at < len(data):
                lba, inside = divmod(offset + at, 2048)
                count = min(2048 - inside, len(data) - at)
                if lba not in patches:
                    patches[lba] = bytearray(disc.sector(lba) if lba < cut else bytes(2048))
                patches[lba][inside:inside + count] = data[at:at + count]
                at += count
        for entry, data in resources:
            rec = files[entry["path"]]
            capacity = (rec["size"] + 2047) // 2048 * 2048
            lba = rec["lba"]
            if len(data) > capacity:
                if not entry["relocate"]:
                    raise RomError("resource growth requires reviewed --relocate")
                lba = next_lba
                next_lba += (len(data) + 2047) // 2048
            patch(lba * 2048, data)
            if lba == rec["lba"] and len(data) < rec["size"]:
                patch(lba * 2048 + len(data), bytes(rec["size"] - len(data)))
            offset = records[entry["path"]]["record_offset"]
            patch(offset + 2, lba.to_bytes(4, "little") + lba.to_bytes(4, "big"))
            patch(offset + 10, len(data).to_bytes(4, "little") + len(data).to_bytes(4, "big"))
            new_values = {"lba": lba, "size": len(data), "sectors": (len(data) + 2047) // 2048}
            for ref in entry["references"]:
                if not 0 <= new_values[ref["kind"]] < 1 << (8 * ref["width"]):
                    raise RomError("new resource address/size exceeds its reviewed loader field")
                encoded = new_values[ref["kind"]].to_bytes(ref["width"], ref["endian"])
                record = files[ref["file"]]
                # Source edits and resource-loader edits cannot silently compete.
                old = reader(baseline, record)(ref["offset"], ref["width"])
                if reader(disc, record)(ref["offset"], ref["width"]) != old:
                    raise RomError("source changes overlap a resource loader reference")
                patch(record["lba"] * 2048 + ref["offset"], encoded)
                references.append(dict(ref, value=new_values[ref["kind"]]))
            changed.append({"path": entry["path"], "lba": lba, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        for (name, sector), replacements in archives.items():
            rec = files[name]
            data, members = psx_hbd.replace(reader(disc, rec), rec["size"], sector, replacements)
            patch(rec["lba"] * 2048 + sector * 2048, data)
            archive_changes.append({"path": name, "sector": sector, "size": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest(), "members": members})
        inserted = next_lba - cut
        if chd_growth:
            inserted = (next_lba + 3) // 4 * 4 - cut
        tail_output_sha = tail_sha
        if chd_growth:
            from .psx_chd_tracks import retimed_tail_digest
            expected_size, tail_output_sha = retimed_tail_digest(stream, next_lba)
            if expected_size != tail_size:
                raise RomError("retimed CHD audio size differs")
        if inserted:
            pvd = disc.sector(16)
            old_blocks = int.from_bytes(pvd[80:84], "little")
            if pvd[80:84] != pvd[84:88][::-1] or old_blocks > cut:
                raise RomError("ISO volume bounds disagree with the first data track")
            patch(16 * 2048 + 80, next_lba.to_bytes(4, "little") + next_lba.to_bytes(4, "big"))
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".psx-assets-", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            if media.get("kind") == "chd":
                from .chd_write import rewrite
                if inserted:
                    from .psx_chd_tracks import image
                    mode = 1 if disc.skip == 16 else 2
                    proof = rewrite(output, temporary, {}, image=lambda source: image(
                        source, cut, next_lba, patches, lambda data, lba: _raw_sector(data, lba, mode, 2448)))
                else:
                    physical_patches = {}
                    for lba, payload in patches.items():
                        stream.seek(lba * disc.size)
                        physical_patches[lba * disc.size] = psx_sector.replace(stream.read(disc.size), payload)
                    proof = rewrite(output, temporary, physical_patches)
            else:
                mode = 1 if disc.skip == 16 else 2
                cut_at = physical_offset + cut * disc.size
                with output.open("rb") as source, temporary.open("w+b") as dest:
                    remaining = cut_at
                    while remaining:
                        data = source.read(min(1 << 20, remaining))
                        if not data:
                            raise RomError("truncated data track during resize")
                        dest.write(data)
                        remaining -= len(data)
                    for lba in range(cut, next_lba):
                        dest.write(_raw_sector(bytes(patches.pop(lba, bytes(2048))), lba, mode, disc.size))
                    shutil.copyfileobj(source, dest, 1 << 20)
                    for lba, payload in patches.items():
                        position = physical_offset + lba * disc.size
                        source.seek(position)
                        old = source.read(disc.size)
                        dest.seek(position)
                        dest.write(bytes(payload) if disc.size == 2048 else psx_sector.replace(old, payload))
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    # Windows cannot replace a destination that still has our read handle open.
    try:
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    if cue:
        _, data = cue_shift(cue[1], media["primary"], inserted)
        # output's parent can be a nested track directory; derive the media root.
        media_root = _media_root(output, media["primary"])
        psx_media.inside(media_root, cue[0]["name"]).write_bytes(data)
    return {"format": 1, "original_sha256": layout["sha256"], "insert_lba": cut, "insert_frames": inserted,
            "data_frames": next_lba, "tail_size": tail_size, "tail_sha256": tail_sha,
            "tail_output_sha256": tail_output_sha,
            **({"chd": proof} if media.get("kind") == "chd" else {}),
            "output_size": output.stat().st_size, "files": changed, "archives": archive_changes, "references": references}


def verify(root, meta, output, report):
    layout = meta["disc"]["layout"]
    if report.get("format") != 1 or report.get("original_sha256") != layout["sha256"] or output.stat().st_size != report["output_size"]:
        raise RomError("resource build report differs from its pinned input or output")
    media = layout.get("media", {})
    original = root / meta["disc"]["image"]
    cue = _cue(root, meta)
    expected_tail = report["tail_size"], report["tail_sha256"]
    with opened(original, layout) as (_, stream):
        stream.seek(0, 2)
        cut = stream.tell() // layout["sector_size"]
        if cue:
            first, expected_cue = cue_shift(cue[1], media["primary"], report["insert_frames"])
            if first is not None:
                cut = first - media.get("offset", 0) // layout["sector_size"]
            media_root = _media_root(output, media["primary"])
            for item in media["companions"]:
                copied = psx_media.inside(media_root, item["name"])
                if item["name"] == cue[0]["name"]:
                    if copied.read_bytes() != expected_cue:
                        raise RomError("modified CUE indices or metadata differ")
                elif psx_media.record(copied, item["name"]) != item:
                    raise RomError("modified disc lost an original companion audio track")
        if media.get("kind") == "chd" and report["insert_frames"]:
            from .psx_chd_tracks import tracks, retimed_tail_digest
            cut = tracks(stream)[0]["padded"]
            expected_tail = retimed_tail_digest(stream, report["data_frames"])
        if cut != report["insert_lba"] or _tail_hash(stream, cut * layout["sector_size"]) != (report["tail_size"], report["tail_sha256"]):
            raise RomError("resource insertion boundary differs from its original track layout")
        if report.get("tail_output_sha256", report["tail_sha256"]) != expected_tail[1]:
            raise RomError("retimed audio hash differs from its original track proof")
    with opened(output, layout) as (disc, stream):
        if (disc.size, disc.skip) != (layout["sector_size"], layout["skip"]):
            raise RomError("resource authoring changed the disc sector format")
        if _tail_hash(stream, (report["insert_lba"] + report["insert_frames"]) * disc.size) != expected_tail:
            raise RomError("resource authoring changed retained audio or trailing track bytes")
        stream.seek(0, 2)
        if media.get("kind") != "chd" and output.stat().st_size != layout["original_size"] + report["insert_frames"] * disc.size:
            raise RomError("resource output size disagrees with its track growth")
        actual = psx_disc.inventory(disc, stream.tell())
        expected = [dict(r) for r in layout["files"]]
        for item in report["files"]:
            record = next(r for r in expected if r["path"] == item["path"])
            record.update(lba=item["lba"], size=item["size"])
            data = reader(disc, record)(0, record["size"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise RomError("modified resource hash differs")
        if actual != expected:
            raise RomError("modified ISO directory differs from reviewed resource changes")
        for item in report["archives"]:
            record = next(r for r in actual if r["path"] == item["path"])
            read = reader(disc, record)
            if hashlib.sha256(read(item["sector"] * 2048, item["size"])).hexdigest() != item["sha256"]:
                raise RomError("modified archive block hash differs")
        for ref in report["references"]:
            record = next(r for r in actual if r["path"] == ref["file"])
            if int.from_bytes(reader(disc, record)(ref["offset"], ref["width"]), ref["endian"]) != ref["value"]:
                raise RomError("modified loader reference differs")
        if report["insert_frames"]:
            pvd = disc.sector(16)
            if int.from_bytes(pvd[80:84], "little") != report["data_frames"] or pvd[80:84] != pvd[84:88][::-1]:
                raise RomError("modified ISO volume bounds differ")
        if media.get("kind") == "chd":
            from .chd import Chd
            from .psx_chd_tracks import metadata
            with Chd(original) as source:
                expected_meta = metadata(source, report["data_frames"]) if report["insert_frames"] else source.metadata
                if stream.metadata != expected_meta or stream.logical != source.logical + report["insert_frames"] * 2448 or \
                        (stream.hunkbytes, stream.unitbytes) != (source.hunkbytes, source.unitbytes):
                    raise RomError("modified CHD track geometry differs from its reviewed growth")
            if psx_disc.digest(stream) != (report["chd"]["logical_size"], report["chd"]["decoded_sha256"]):
                raise RomError("modified CHD decoded frames differ from their build proof")
