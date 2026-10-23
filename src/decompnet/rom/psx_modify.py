"""Fixed-extent PS1 program updates with raw-sector error correction."""

from contextlib import ExitStack
import hashlib
from pathlib import Path
import shutil

from .n64 import RomError
from . import psx_disc, psx_media, psx_sector


def rebuild(original, rebuilt, layout, output):
    original, output = Path(original), Path(output)
    if original.resolve() == output.resolve():
        raise RomError("a modified disc must have a separate output path")
    output.unlink(missing_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        baseline = psx_disc.analysis(original, layout)
        if len(rebuilt) != len(baseline):
            raise RomError("a PS1 mod cannot change analysis-image or file sizes")
        media = layout.get("media")
        if media and media["kind"] == "chd":
            if rebuilt != baseline:
                raise RomError("changed CHD output requires a lossless track/audio recompression adapter; import BIN/CUE instead")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, temporary)
            temporary.replace(output)
            return {"changed_sectors": 0, "files": []}
        sectors, files, cursor = {}, [], 0
        raw_layout = psx_media.unpack(layout) if media else layout
        with ExitStack() as stack:
            physical = stack.enter_context(original.open("rb"))
            view = stack.enter_context(psx_media.decoded(original, media)) if media else physical
            disc = psx_disc.verify(view, raw_layout)
            for mapping in sorted(layout["maps"], key=lambda m: m["analysis_offset"]):
                start, stop = mapping["analysis_offset"], mapping["analysis_offset"] + mapping["size"]
                if rebuilt[cursor:start] != baseline[cursor:start]:
                    raise RomError("a PS1 mod changed unmapped analysis bytes")
                cursor = stop
                data, old = rebuilt[start:stop], baseline[start:stop]
                if data == old:
                    continue
                if mapping.get("codec", "raw") != "raw" or mapping.get("relocations"):
                    raise RomError("changed encoded or runtime-relocated modules require a storage/loader authoring adapter")
                prefix = max(mapping.get("code_at", 0), 0x800 if old.startswith(b"PS-X EXE") else 0)
                if data[:prefix] != old[:prefix]:
                    raise RomError("a PS1 mod cannot change executable headers or module prefixes")
                files.append(mapping["path"])
                offset = mapping.get("file_offset", 0)
                for at in range(0, len(data)):
                    if data[at] == old[at]:
                        continue
                    lba, inside = divmod(offset + at, 2048)
                    lba += mapping["lba"]
                    payload = sectors.setdefault(lba, bytearray())
                    if not payload:
                        payload += disc.sector(lba)
                    payload[inside] = data[at]
            if rebuilt[cursor:] != baseline[cursor:]:
                raise RomError("a PS1 mod changed unmapped analysis bytes")
            output.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w+b") as destination:
                physical.seek(0)
                shutil.copyfileobj(physical, destination, 1 << 20)
                for lba, data in sorted(sectors.items()):
                    position = (media.get("offset", 0) if media else 0) + lba * disc.size
                    physical.seek(position)
                    original_sector = physical.read(disc.size)
                    sector = bytes(data) if disc.size == 2048 else psx_sector.replace(original_sector, data)
                    destination.seek(position)
                    destination.write(sector)
                destination.flush()
                if destination.seek(0, 2) != layout["original_size"]:
                    raise RomError("a PS1 mod changed its pinned disc size")
        temporary.replace(output)
        return {"changed_sectors": len(sectors), "files": files,
                "analysis_sha256": hashlib.sha256(rebuilt).hexdigest()}
    finally:
        temporary.unlink(missing_ok=True)
