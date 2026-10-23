"""Pinned CUE track sets and CHD containers for exact PS1 matching builds.

Matching retains the original container after every imported program rebuilds
exactly. Separate mod builds use psx_modify and lossless CHD frame rewriting.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from .n64 import RomError


def relative(name):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(p in (".", "..") or ":" in p for p in path.parts):
        raise RomError("CUE files must reference relative tracks inside their own directory")
    return path.as_posix()


def inside(root, name):
    path = root / relative(name)
    if root.resolve() not in path.resolve().parents:
        raise RomError("a PS1 media file is outside its project")
    return path


def record(path, name):
    from .psx_disc import digest
    with path.open("rb") as src:
        size, sha = digest(src)
    return {"name": name, "size": size, "sha256": sha}


def cue(path):
    if path.stat().st_size > 1 << 20:
        raise RomError("CUE sheets must be at most 1 MiB")
    text = path.read_text(encoding="utf-8-sig")
    files, tracks, current = [], [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if m := re.fullmatch(r'FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY', line, re.I):
            current = relative(m[1] or m[2])
            if current not in files:
                files.append(current)
        elif m := re.fullmatch(r"TRACK\s+(\d+)\s+(AUDIO|MODE1/2048|MODE1/2352|MODE2/2352)", line, re.I):
            if current is None or int(m[1]) != len(tracks) + 1:
                raise RomError("CUE tracks must follow a FILE and use consecutive track numbers")
            tracks.append({"file": current, "mode": m[2].upper(), "indices": {}})
        elif m := re.fullmatch(r"INDEX\s+(\d+)\s+(\d+):(\d{2}):(\d{2})", line, re.I):
            index, minute, second, frame = map(int, m.groups())
            if not tracks or index in tracks[-1]["indices"] or second >= 60 or frame >= 75:
                raise RomError("invalid or duplicate CUE index")
            tracks[-1]["indices"][index] = (minute * 60 + second) * 75 + frame
        elif not re.fullmatch(r"(?:REM(?:\s+.*)?|(?:TITLE|PERFORMER|SONGWRITER|CATALOG|ISRC|FLAGS)\s+.+|(?:PRE|POST)GAP\s+\d+:\d{2}:\d{2})", line, re.I):
            raise RomError("unsupported CUE statement: " + line[:100])
    data = [t for t in tracks if t["mode"] != "AUDIO"]
    if len(data) != 1 or not tracks or data[0] is not tracks[0] or len(tracks) > 99:
        raise RomError("CUE matching requires one first data track followed by optional audio tracks")
    for track in tracks:
        indices = track["indices"]
        if 1 not in indices or list(indices) != sorted(indices) or list(indices.values()) != sorted(indices.values()):
            raise RomError("CUE tracks require ordered indices and INDEX 01")
    primary = data[0]["file"]
    sector = 2048 if data[0]["mode"] == "MODE1/2048" else 2352
    positions = {}
    for track in tracks:
        if track["file"] in positions and min(track["indices"].values()) < positions[track["file"]]:
            raise RomError("CUE track indices move backwards within a shared file")
        positions[track["file"]] = max(track["indices"].values())
        if track["mode"] == "AUDIO" and track["file"] == primary and sector != 2352:
            raise RomError("shared data/audio CUE files require 2352-byte sectors")
    if set(files) != set(positions):
        raise RomError("every CUE file must contain a track")
    records = []
    for name in files:
        source = inside(path.parent, name)
        if not source.is_file() or source.stat().st_size % (sector if name == primary else 2352):
            raise RomError("missing or partial-sector CUE track: " + name)
        records.append(record(source, name))
    for track in tracks:
        size = next(r["size"] for r in records if r["name"] == track["file"])
        if max(track["indices"].values()) * (sector if track["file"] == primary else 2352) >= size:
            raise RomError("a CUE index exceeds its track file")
    if path.name in files:
        raise RomError("a CUE sheet cannot also be a track")
    return {"kind": "cue", "primary": primary, "sector_size": sector, "mode": data[0]["mode"],
            "offset": data[0]["indices"][1] * sector,
            "companions": [record(path, path.name), *[r for r in records if r["name"] != primary]]}


class Offset:
    def __init__(self, source, offset):
        self.source, self.offset, self.pos = source, offset, 0
        source.seek(0, 2)
        self.length = source.tell() - offset
        if self.length <= 0:
            raise RomError("CUE data track starts outside its file")

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.length + offset
        if self.pos < 0:
            raise RomError("negative CUE track seek")
        return self.pos

    def tell(self):
        return self.pos

    def read(self, size=-1):
        self.source.seek(self.offset + self.pos)
        size = self.length - self.pos if size < 0 else min(size, max(0, self.length - self.pos))
        result = self.source.read(size)
        self.pos += len(result)
        return result


@contextmanager
def decoded(path, media):
    if media["kind"] == "chd":
        from .chd import Chd
        with Chd(path) as source:
            yield source
    elif media["kind"] == "cue":
        with path.open("rb") as source:
            yield Offset(source, media["offset"])
    else:
        raise RomError("unknown PS1 media container")


def wrap(layout, primary, media):
    from .psx_disc import digest
    media = dict(media, decoded_size=layout["original_size"], decoded_sha256=layout["sha256"])
    with primary.open("rb") as source:
        size, sha = digest(source)
    return dict(layout, original_size=size, sha256=sha, media=media,
                identity=hashlib.sha256((sha + json.dumps(media, sort_keys=True)).encode()).hexdigest())


def unpack(layout):
    media = layout["media"]
    return dict(layout, original_size=media["decoded_size"], sha256=media["decoded_sha256"])


def verify_files(original, layout):
    from .psx_disc import digest
    with original.open("rb") as source:
        if digest(source) != (layout["original_size"], layout["sha256"]):
            raise RomError("the original PS1 media container differs")
    media = layout["media"]
    for item in media.get("companions", []):
        source = inside(original.parent / media["directory"], item["name"])
        with source.open("rb") as stream:
            if digest(stream) != (item["size"], item["sha256"]):
                raise RomError("a retained CUE or audio track differs: " + item["name"])


def snapshot(data, picked, workdir):
    layout = picked.disc
    media = layout.get("media")
    source = Path(data) if isinstance(data, (str, Path)) else None
    original = workdir / ("original-disc.chd" if media and media["kind"] == "chd" else "original-disc.bin")
    primary = inside(source.parent, media["primary"]) if media and media["kind"] == "cue" else source
    if primary:
        shutil.copyfile(primary, original)
    else:
        original.write_bytes(data)
    if media:
        media["directory"] = "original-media"
        for item in media.get("companions", []):
            target = inside(workdir / media["directory"], item["name"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inside(source.parent, item["name"]), target)
    return original


def companions(original, layout, output):
    """Copy retained CUE/audio files after their pinned hashes have been checked."""
    verify_files(original, layout)
    media = layout["media"]
    for item in media.get("companions", []):
        dest = inside(output, item["name"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(original.parent / media["directory"], item["name"]), dest)
