"""GB/GBC assembly projects using the shared claim and attempt bookkeeping."""

import json
import time
from pathlib import Path

from ..network import NetworkError
from ..rom import gb, match_gb, sm83


def _claim_ranges(raw, regions):
    """Bound generated submissions without splitting a variable-length instruction."""
    for region in regions:
        start, size = region.start.offset, 0
        for insn in sm83.disassemble(raw[start:start + region.size], region.start.cpu):
            if size + len(insn.data) > 2048:
                yield gb.CodeRange(gb.Address.from_offset(start), size)
                start, size = start + size, 0
            size += len(insn.data)
        if size:
            yield gb.CodeRange(gb.Address.from_offset(start), size)


def _refs(code, addr, info):
    result = []
    for insn in sm83.disassemble(code, addr.cpu):
        if insn.flow == "call" and insn.target is not None:
            target = gb.resolve(addr, insn.target, info)
            if target is not None:
                result.append([insn.address - addr.cpu, 83, target.key])
    return result


def _insert(db, pid, raw, region, info, name=None):
    addr = region.start
    name = name or f"func_{addr.key:08X}"
    code = raw[addr.offset:addr.offset + region.size]
    text = match_gb.source(raw, addr.key, region.size, name)
    db.execute("INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,unit,vram,rom_offset) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (pid, name, region.size, len(sm83.disassemble(code, addr.cpu)), code,
                                                json.dumps(_refs(code, addr, info)), text, text, f"bank_{addr.bank:03X}", addr.key, addr.offset))
    db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?)",
               (pid, name, addr.key, region.size, "func"))
    return name


def import_rom(net, picked, slug, workdir, log):
    info, raw = picked.info, picked.data
    regions, notes = gb.discover(raw)
    regions = list(_claim_ranges(raw, regions))
    config = {"kind": "rom", "platform": picked.platform, "arch": "sm83", "big_endian": False,
              "rom": {**info, "file": picked.filename, "program": picked.filename},
              "segments": [{"name": f"bank_{bank:03X}", "rom_start": bank * gb.BANK_SIZE,
                            "rom_end": (bank + 1) * gb.BANK_SIZE,
                            "vram": gb.Address(bank, gb.BANK_SIZE if bank else 0).key} for bank in range(info["banks"])],
              "compiler": {"toolchain": "rgbds", "language": "asm", "flags": [], "timeout": 20},
              "analysis_notes": notes, "context": {"file": None},
              "legal": {"basis": "personal-copy", "license": "personal use only",
                        "statement": "imported by the owner of this copy, who confirmed it was legally obtained",
                        "confirmed_at": time.time()}}
    with net.store.tx() as db:
        pid = db.execute("INSERT INTO projects(slug,name,description,arch,big_endian,root,config) VALUES(?,?,?,?,?,?,?)",
                         (slug, info["title"], f"{info['mapper']} · {info['banks']} banks · RGBDS assembly",
                          "sm83", 0, str(workdir), json.dumps(config))).lastrowid
        for region in regions:
            _insert(db, pid, raw, region, info)
        db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                   "VALUES(?,?,?,?,?,?,?)", (pid, 1, "; context.inc: shared RGBDS numeric constants (DEF name EQU value).\n"
                                             "; External project labels are linked at their known bank/CPU address.\n",
                                             None, "assembly context", time.time(), ""))
        for note in notes:
            db.execute("INSERT INTO notes(project_id,text,created_at) VALUES(?,?,?)", (pid, note, time.time()))
        net._event(db, pid, None, "import", f"{len(regions)} assembly ranges; unmapped bytes retained in owner base ROM")
    log(f"ready: {len(regions)} assembly ranges to review and verify; bank switches may need explicit entries")
    return slug


def split_or_add(net, agent, proj, fn, at, new_name):
    from ..rom.symbols import IDENT

    try:
        addr = gb.Address.parse(at) if ":" in at else gb.Address.from_key(int(at, 16))
    except ValueError as error:
        raise NetworkError(f"use bank:CPU address, e.g. 02:4000: {error}") from error
    name = new_name.strip() or f"func_{addr.key:08X}"
    syms = net.symbols(proj["id"])
    if not IDENT.fullmatch(name) or name in syms.by_name:
        raise NetworkError("new name must be a free identifier")
    raw, _ = net._rom(proj)
    info = net.cfg(proj)["rom"]
    existing = net.store.all("SELECT * FROM functions WHERE project_id=?", proj["id"])
    offset = addr.key - fn["vram"]
    if 0 < offset < fn["size"]:
        if fn["status"] == "matched":
            raise NetworkError("a verified range cannot be split")
        held = net.store.one("SELECT agent_id FROM claims WHERE function_id=?", fn["id"])
        if held and held["agent_id"] != agent.id:
            raise NetworkError("this range is claimed by another agent")
        boundaries = {i.address for i in sm83.disassemble(fn["target"], fn["vram"] & 0xFFFF)}
        if addr.cpu not in boundaries:
            raise NetworkError("split address enters an instruction operand")
        text = match_gb.source(raw, fn["vram"], offset, fn["name"])
        with net.store.tx() as db:
            db.execute("UPDATE functions SET size=?,n_insns=?,target=?,asm=?,seed=?,relocs=?,best_score=NULL,best_source=NULL,"
                       "best_agent_id=NULL WHERE id=?", (offset, len(sm83.disassemble(fn["target"][:offset])),
                                                        fn["target"][:offset], text, text,
                                                        json.dumps(_refs(fn["target"][:offset], gb.Address.from_key(fn["vram"]), info)), fn["id"]))
            db.execute("UPDATE symbols SET size=? WHERE project_id=? AND name=?", (offset, proj["id"], fn["name"]))
            _insert(db, proj["id"], raw, gb.CodeRange(addr, fn["size"] - offset), info, name)
            net._event(db, proj["id"], agent.id, "split", f"{fn['name']} / {name}")
        result = f"✅ split assembly range at {addr}: {name}"
    else:
        try:
            regions, notes = gb.discover(raw, [addr])
        except gb.CartridgeError as error:
            raise NetworkError(str(error)) from error
        additions = []
        for region in _claim_ranges(raw, regions):
            start, end = region.start.offset, region.start.offset + region.size
            overlaps = [r for r in existing if r["rom_offset"] < end and start < r["rom_offset"] + r["size"]]
            if any(r["rom_offset"] <= start and end <= r["rom_offset"] + r["size"] for r in overlaps):
                continue
            if overlaps:
                raise NetworkError("new entry overlaps a known range; split that range at an instruction boundary")
            additions.append(region)
        if not additions:
            raise NetworkError("entry found no additional code ranges; it is already covered or needs a reviewed layout")
        names = []
        with net.store.tx() as db:
            for region in additions:
                names.append(_insert(db, proj["id"], raw, region, info, name if region.start == addr else None))
            for note in notes:
                db.execute("INSERT INTO notes(project_id,text,created_at) VALUES(?,?,?)", (proj["id"], note, time.time()))
            net._event(db, proj["id"], agent.id, "split", f"added assembly entry {addr}: {', '.join(names)}")
        result = f"✅ added {len(names)} assembly range(s) from {addr}: {', '.join(names)}"
    net._syms.pop(proj["id"], None)
    net._xrefs.pop(proj["id"], None)
    net._ops.pop(proj["id"], None)
    return result


def export_rom(net, slug, out, log):
    """Fresh exports retain edited previous exports; rejudge saved matches before copying them."""
    from ..rom.export_gb import export
    from ..rom.export_gb_build import build

    proj = net._project(slug)
    cfg = net.cfg(proj)
    rows = net.store.all("SELECT * FROM functions WHERE project_id=? ORDER BY rom_offset", proj["id"])
    root, index = out, 2
    while root.exists() and any(root.iterdir()):
        root = out.with_name(f"{out.name}-{index}")
        index += 1
    raw, _ = net._rom(proj)
    manifest = export(raw, root, entries=[], ranges=[gb.CodeRange(gb.Address.from_key(r["vram"]), r["size"]) for r in rows])
    matched, fallback = 0, []
    main = (root / "main.asm").read_text(encoding="utf-8")
    manifest["units"] = []
    for row, region in zip(rows, manifest["code_ranges"]):
        (root / region["path"]).write_text(match_gb.source(raw, row["vram"], row["size"], row["name"]),
                                           encoding="utf-8", newline="\n")
        if row["status"] != "matched":
            continue
        broken = net.regression_test(proj, None, only=[row], header_for=lambda fn: net._context(proj["id"], fn["unit"])["header"])
        if broken:
            fallback.append(row["name"])
            log(f"{row['name']}: saved assembly no longer verifies; retaining regenerated baseline")
            continue
        context = net._context(proj["id"], row["unit"])["header"]
        (root / region["path"]).write_text(context + "\n" + row["matched_source"], encoding="utf-8", newline="\n")
        main = main.replace(f'INCLUDE "{region["path"]}"', f'; Verified range compiled separately: {region["path"]}')
        manifest["units"].append(region["path"])
        matched += 1
    main += "\n" + match_gb.externals(net.symbols(proj["id"]), {r["name"] for r in rows}) + "\n"
    (root / "main.asm").write_text(main, encoding="utf-8", newline="\n")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    result = build(root, Path(proj["root"]) / cfg["rom"]["file"])
    log(f"verified complete cartridge: {result['size']} bytes")
    return {"path": str(root), "identical": True, "matched": matched, "functions": len(rows), "fallback": fallback,
            "language": "asm", "assembly_bytes": manifest["assembly_bytes"], "base_bytes": manifest["base_bytes"]}
