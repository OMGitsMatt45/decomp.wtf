"""Native assembly workflow for filesystem-free DS and apploader-only utilities."""

import json
import re
import shutil
import time
from pathlib import Path

from .. import toolchains
from ..elfobj import FunctionObj
from ..network import NetworkError
from ..rom import boot, boot_build


def import_rom(net, picked, slug, workdir, log):
    info, image = picked.info, picked.data
    meta, now = info["boot_utility"], time.time()
    arch = meta["arch"]
    tid = "gc-wii-binutils" if arch == "ppc" else "binutils-arm"
    program = ("powerpc-eabi-as" if arch == "ppc" else "bin/arm-none-eabi-as") + (".exe" if toolchains.current_platform().startswith("windows-") else "")
    flags = ["-mgekko", "-mregnames"] if arch == "ppc" else ["-mcpu=arm946e-s"]
    ranges = boot.discover(image, meta)
    cfg = {"kind": "rom", "platform": picked.platform, "big_endian": picked.big_endian,
           "rom": {**info, "file": picked.filename, "program": picked.filename}, "segments": meta["segments"],
           "compiler": {"toolchain": tid, "language": "asm", "assembly_dialect": "gnu", "flags": flags,
                        "cmd": ["{tc}/" + program, *flags, "-I{include}", "-o", "{obj}", "{src}"]},
           "context": {"file": None}, "legal": {"basis": "personal-copy", "license": "personal use only",
                         "statement": "imported by the owner, who confirmed this copy was legally obtained", "confirmed_at": now}}
    with net.store.tx() as db:
        pid = db.execute("INSERT INTO projects(slug,name,description,arch,big_endian,root,config) VALUES(?,?,?,?,?,?,?)",
                         (slug, info["title"], f"{meta['scope']} · GNU assembly · {len(ranges)} instruction ranges",
                          arch, int(picked.big_endian), str(workdir), json.dumps(cfg))).lastrowid
        for region in ranges:
            code = image[region["offset"]:region["offset"] + region["size"]]
            source = boot.assembly(code, region["addr"], region["name"], arch, region["thumb"])
            db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,unit,vram,rom_offset) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (pid, region["name"], region["size"], len(code) // (2 if region["thumb"] else 4),
                        code, "[]", source, source, region["segment"], region["addr"], region["offset"]))
            db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?)",
                       (pid, region["name"], region["addr"], region["size"], "func"))
        db.execute("INSERT INTO context_versions(project_id,version,header,message,created_at,unit) VALUES(?,?,?,?,?,?)",
                   (pid, 1, "/* Shared GNU assembly constants. */\n", "assembly context", now, ""))
        net._event(db, pid, None, "import", f"{len(ranges)} reachable instruction ranges; scope: {meta['scope']}")
    log(f"ready: {len(ranges)} assembly ranges ({sum(r['size'] for r in ranges)} bytes); rebuilding {meta['scope']}")
    return slug


def symbols(net, proj):
    result = {s.name: s.address for s in net.symbols(proj["id"]).by_name.values()}
    rows = net.store.all("SELECT asm,vram,size FROM functions WHERE project_id=?", proj["id"])
    for row in rows:
        for value in re.findall(r"__boot_([0-9A-F]{8})", row["asm"]):
            address = int(value, 16)
            thumb = any(other["vram"] <= address < other["vram"] + other["size"] and ".thumb\n" in other["asm"] for other in rows)
            result[f"__boot_{value}"] = address | int(thumb)
    return result


def split_range(net, agent, proj, fn, at, new_name):
    from ..rom.symbols import IDENT

    try:
        address = int(at, 16)
    except ValueError:
        raise NetworkError("use a hexadecimal program address") from None
    name = new_name.strip() or f"boot_{address:08X}"
    if not IDENT.fullmatch(name) or name in net.symbols(proj["id"]).by_name:
        raise NetworkError("new name must be a free identifier")
    thumb = ".thumb\n" in fn["asm"]
    boundaries = {i.address for i in boot.disassembler(proj["arch"], thumb).disasm(fn["target"], fn["vram"])}
    offset = address - fn["vram"]
    if not 0 < offset < fn["size"] or address not in boundaries:
        raise NetworkError("split must be at an instruction boundary inside this range")
    if fn["status"] == "matched":
        raise NetworkError("a verified range cannot be split")
    held = net.store.one("SELECT agent_id FROM claims WHERE function_id=?", fn["id"])
    if held and held["agent_id"] != agent.id:
        raise NetworkError("this range is claimed by another agent")
    head, tail = fn["target"][:offset], fn["target"][offset:]
    sources = [boot.assembly(code, addr, label, proj["arch"], thumb) for code, addr, label in
               ((head, fn["vram"], fn["name"]), (tail, address, name))]
    width = 2 if thumb else 4
    with net.store.tx() as db:
        db.execute("UPDATE functions SET size=?,n_insns=?,target=?,asm=?,seed=?,best_score=NULL,best_source=NULL,"
                   "best_agent_id=NULL WHERE id=?", (len(head), len(head) // width, head, sources[0], sources[0], fn["id"]))
        db.execute("UPDATE symbols SET size=? WHERE project_id=? AND name=?", (len(head), proj["id"], fn["name"]))
        db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,unit,vram,rom_offset) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (proj["id"], name, len(tail), len(tail) // width, tail, "[]",
                    sources[1], sources[1], fn["unit"], address, fn["rom_offset"] + offset))
        db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?)",
                   (proj["id"], name, address, len(tail), "func"))
        net._event(db, proj["id"], agent.id, "split", f"{fn['name']} / {name}")
    net._syms.pop(proj["id"], None)
    net._xrefs.pop(proj["id"], None)
    net._ops.pop(proj["id"], None)
    return f"✅ split assembly range at 0x{address:08X}: {name}"


def evaluate(net, fn, proj, obj):
    from ..compiler import _SLOTS, run_in
    from ..project import compiler_config
    import subprocess
    import tempfile

    cfg = compiler_config(Path(proj["root"]), net.cfg(proj))
    arch = proj["arch"]
    as_path = Path(cfg.cmd[0])
    linker = str(as_path.with_name(as_path.name.replace("-as", "-ld")))
    with tempfile.TemporaryDirectory(prefix="decomp-boot-link-") as tmp:
        root = Path(tmp)
        (root / "candidate.o").write_bytes(obj)
        (root / "candidate.ld").write_text(boot_build.script(fn["vram"], symbols(net, proj)), encoding="utf-8")
        try:
            with _SLOTS:
                result = run_in(cfg, root, [linker, "-T", "candidate.ld", "-o", "candidate.elf", "candidate.o"])
            if result.returncode:
                return None, False, [(result.stdout + result.stderr)[-2500:]]
            code = boot_build.linked_code((root / "candidate.elf").read_bytes(), fn["vram"], fn["size"], fn["name"])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return None, False, [str(error)]
    thumb = ".thumb\n" in fn["asm"]
    candidate = FunctionObj(fn["name"], "thumb" if thumb else arch, arch == "ppc", code, [])
    return candidate, code == fn["target"], []


def export_rom(net, slug, out, log):
    import hashlib

    proj = net._project(slug)
    cfg = net.cfg(proj)
    meta = cfg["rom"]["boot_utility"]
    image, _ = net._rom(proj)
    root, index = out, 2
    while root.exists() and any(root.iterdir()):
        root = out.with_name(f"{out.name}-{index}")
        index += 1
    (root / "src").mkdir(parents=True)
    ranges = []
    rows = net.store.all("SELECT * FROM functions WHERE project_id=? ORDER BY rom_offset", proj["id"])
    matched = 0
    for row in rows:
        source = boot.assembly(row["target"], row["vram"], row["name"], proj["arch"], ".thumb\n" in row["asm"])
        if row["status"] == "matched" and row["matched_source"]:
            context = net._context(proj["id"], row["unit"])["header"]
            compiled = net._compile(proj, context, row["matched_source"])
            if not compiled.ok or not evaluate(net, row, proj, compiled.obj)[1]:
                raise NetworkError(f"{row['name']}: saved assembly no longer verifies")
            source = context + "\n" + row["matched_source"]
            matched += 1
        path = f"src/{row['name']}.s"
        (root / path).write_text(source, encoding="utf-8", newline="\n")
        ranges.append({"name": row["name"], "addr": row["vram"], "offset": row["rom_offset"],
                       "size": row["size"], "source": path})
    manifest = {"scope": meta["scope"], "arch": proj["arch"], "image": cfg["rom"]["file"], "output": cfg["rom"]["file"],
                "sha256": hashlib.sha256(image).hexdigest(), "input_sha256": meta["input_sha256"],
                "ranges": ranges, "symbols": symbols(net, proj), "assembly_bytes": sum(r["size"] for r in ranges)}
    manifest["base_bytes"] = len(image) - manifest["assembly_bytes"]
    (root / manifest["image"]).write_bytes(image)
    (root / "build.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copyfile(Path(boot_build.__file__), root / "build.py")
    (root / ".gitignore").write_text(f"build/\n{manifest['image']}\n__pycache__/\n", encoding="utf-8")
    (root / "README.md").write_text(
        f"# {proj['name']} boot utility\n\n"
        f"GNU assembly workflow; scope: **{meta['scope']}**. Run `python build.py` with decomp.wtf installed.\n"
        f"The builder assembles {manifest['assembly_bytes']} reachable instruction bytes from `src/` and retains "
        f"{manifest['base_bytes']} unknown/header/data bytes from your SHA-256-verified base image. "
        "Every output byte must match. Editing any instruction changes the check result.\n\n"
        "These are assembly ranges, not recovered C/C++ functions. Indirect control flow may need review. "
        "For apploaders the original disc container is not rebuilt; this checks its extracted executable boot program. "
        "Keep your base image private and out of Git.\n", encoding="utf-8")
    result = boot_build.build(root)
    log(f"identical: {meta['scope']}, {result['size']} bytes; {manifest['assembly_bytes']} editable assembly bytes")
    return {"path": str(root), "identical": True, "matched": matched, "functions": len(rows), "language": "asm",
            "scope": meta["scope"], "assembly_bytes": manifest["assembly_bytes"], "base_bytes": manifest["base_bytes"]}
