"""Console access to bounded Heartbeat archive operations."""

import hashlib
from pathlib import Path
import tempfile

from . import psx_hbd, psx_assets, psx_media
from .detect import identify
from .n64 import RomError


def run(args):
    if args.archive_cmd == "replace":
        return psx_assets.stage(args.input_path, args.file, args.input, sector=args.sector, member=args.member)
    path = args.input_path.resolve()
    picked = identify(path)
    if picked.platform != "psx" or not picked.disc or not picked.disc.get("supported"):
        raise RomError("choose a supported PS1 disc image")
    layout = picked.disc
    media = layout.get("media", {})
    primary = psx_media.inside(path.parent, media["primary"]) if media.get("kind") == "cue" else path
    record = next((r for r in layout["files"] if r["path"] == psx_assets.path_name(args.file) and not r["directory"]), None)
    if record is None:
        raise RomError("choose an existing ISO archive file")
    with psx_assets.opened(primary, layout) as (disc, _):
        read = psx_assets.reader(disc, record)
        if args.archive_cmd == "inspect":
            result = psx_hbd.inventory(read, record["size"])
            result.update(path=record["path"], block_count=len(result["blocks"]),
                          member_count=sum(len(b["members"]) for b in result["blocks"]))
            if not args.full:
                del result["blocks"]
            return result
        item = psx_hbd.block(read, record["size"], args.sector)
        if item is None or not 0 <= args.member < len(item["members"]):
            raise RomError("choose an existing Heartbeat archive sector and member index")
        member = item["members"][args.member]
        data = read(member["offset"], member["stored_size"]) if args.stored else psx_hbd.decoded(read, member)
    output = args.output.resolve()
    protected = [path, primary, *[psx_media.inside(path.parent, r["name"]) for r in media.get("companions", [])]]
    if any(output == p.resolve() or output.exists() and output.samefile(p) for p in protected):
        raise RomError("extract archive members to a separate output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.close()
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return {"path": str(output), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "sector": args.sector, "member": args.member, "stored": args.stored}
