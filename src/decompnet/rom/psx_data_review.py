"""Archive reviewed false boot-code targets without losing recovered source."""

import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import uuid

import yaml

from ..network import NetworkError
from ..project import function_config
from . import psx_assets, psx_data, psx_disc, psx_layout, split
from .psx_boundaries import _json_row


def _canonical(mapping):
    """Facts that a data-only review is not allowed to change."""
    return {"segment": mapping["segment"], "path": mapping["path"], "lba": mapping["lba"],
        "file_size": mapping["file_size"], "offset": mapping.get("file_offset", 0),
        "stored_size": mapping.get("stored_size", mapping["size"]), "size": mapping["size"],
        "load": mapping.get("load"), "code_at": mapping.get("code_at", 0),
        "codec": mapping.get("codec", "raw"), "relocations": mapping.get("relocations", []),
        "storage": mapping.get("storage"), "sha256": mapping["sha256"],
        "analysis_offset": mapping["analysis_offset"]}


def _outside_identity(rows, affected):
    return sorted((row["id"], row["unit"], row["vram"], row["rom_offset"], row["size"],
                   hashlib.sha256(row["target"] or b"").hexdigest()) for row in rows if row["id"] not in affected)


def _write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def migrate(net, slug, declaration, *, agent, reason, transfer=True):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        raise NetworkError("provide the reviewed loader/data evidence for this classification")
    project = net.project_row(slug)
    cfg = net.cfg(project)
    if slug in net.links or not net.is_rom(project) or cfg.get("platform") != "psx" or not cfg.get("psx_disc", {}).get("supported"):
        raise NetworkError("reviewed main data requires a local, reconstructable PS1 disc project")
    work = Path(project["root"])
    configs = list(work.glob("*.yaml"))
    if len(configs) != 1:
        raise NetworkError("the original PS1 Splat configuration must be unambiguous")
    config_path, old_text = configs[0], configs[0].read_bytes()
    layout_path = work / "psx-layout.json"
    old_layout = layout_path.read_bytes() if layout_path.exists() else None
    image = (work / cfg["rom"]["file"]).read_bytes()
    original = work / cfg["psx_disc"]["file"]
    if psx_disc.analysis(original, cfg["psx_disc"]) != image:
        raise NetworkError("the retained PS1 disc differs from its original analysis bytes")
    picked = SimpleNamespace(disc=cfg["psx_disc"], overlays=[])
    with psx_assets.opened(original, cfg["psx_disc"]) as (_, stream):
        module_facts = psx_layout.apply(picked, stream, declaration)
    segments = [split.Segment(**segment) for segment in cfg["segments"]]
    layout = psx_disc.bind(picked.disc, [vars(segment) for segment in segments], image)
    if [_canonical(m) for m in layout["maps"]] != [_canonical(m) for m in cfg["psx_disc"]["maps"]]:
        raise NetworkError("a main-data review cannot add, move or change canonical modules; import that layout separately")
    for old, new in zip(cfg["psx_disc"]["maps"], layout["maps"]):
        if any(copy not in new.get("copies", []) for copy in old.get("copies", [])):
            raise NetworkError("a main-data review must retain every established module storage copy")
    for name, facts in module_facts.items():
        if name != "main" and facts != cfg.get("psx_modules", {}).get(name):
            raise NetworkError("a main-data review cannot change canonical module GP, BSS or code boundaries")
    definitions = layout["maps"][0].get("data_ranges", [])
    if any(not psx_data.contains(definitions, item["offset"], item["size"])
           for item in cfg["psx_disc"]["maps"][0].get("data_ranges", [])):
        raise NetworkError("a main-data review must retain all previously reviewed data envelopes")
    if not definitions:
        raise NetworkError("declare at least one reviewed main-data envelope")
    rows = net.store.all("SELECT * FROM functions WHERE project_id=? AND unit='main'", project["id"])
    affected = []
    for row in rows:
        at, size = row["rom_offset"], row["size"]
        if at is None or not size:
            raise NetworkError("a boot target has no original file boundary")
        if not any(at < item["offset"] + item["size"] and item["offset"] < at + size for item in definitions):
            continue
        if not psx_data.contains(definitions, at, size):
            raise NetworkError("a target crosses a reviewed data edge; review and split its boundary explicitly first")
        if image[at:at + size] != row["target"] or size % 4:
            raise NetworkError("an affected boot target differs from its original bytes")
        affected.append(row)
    ids = {row["id"] for row in affected}
    outside = _outside_identity(net.store.all("SELECT * FROM functions WHERE project_id=?", project["id"]), ids)
    main = next((segment for segment in segments if segment.name == "main"), None)
    if main is None:
        raise NetworkError("the original boot module boundary is unavailable")
    load = main.vram - main.rom_start + 0x800
    code_rows = net.store.all("SELECT * FROM functions WHERE project_id=?", project["id"])
    for row in code_rows:
        if row["id"] in ids:
            continue
        at, size = row["rom_offset"], row["size"]
        if at is None or not size or size % 4 or image[at:at + size] != row["target"]:
            raise NetworkError("an outside executable target differs from its original bytes")
        if any(psx_data.contains(definitions, target - load + 0x800, 4)
               for target in psx_data.direct_targets(row["target"], row["vram"])):
            raise NetworkError("outside boot control flow enters the reviewed data; review its classification")
    proposed = yaml.safe_load(old_text)
    psx_data.classify(proposed, definitions)
    new_text = yaml.safe_dump(proposed, sort_keys=False).encode("utf-8")
    token = uuid.uuid4().hex
    backup = work / "data-reviews" / token
    backup.mkdir(parents=True)
    (backup / "original-splat.yaml").write_bytes(old_text)
    if old_layout is not None:
        (backup / "original-layout.json").write_bytes(old_layout)
    wrote_config = False
    wrote_layout = False
    archived_config = None
    try:
        with net.store.tx() as db:
            net._expire_claims(db)
            fresh = db.execute("SELECT * FROM projects WHERE id=?", (project["id"],)).fetchone()
            latest = net.cfg(fresh)
            if {k: v for k, v in latest.items() if k != "function_compilers"} != {k: v for k, v in cfg.items() if k != "function_compilers"}:
                raise NetworkError("the PS1 configuration changed concurrently; retry the data review")
            current = db.execute("SELECT * FROM functions WHERE project_id=?", (project["id"],)).fetchall()
            current_layout = layout_path.read_bytes() if layout_path.exists() else None
            if _outside_identity(current, ids) != outside or config_path.read_bytes() != old_text or current_layout != old_layout:
                raise NetworkError("boot boundaries or Splat configuration changed concurrently; retry the review")
            snapshots = []
            for row in affected:
                saved = db.execute("SELECT * FROM functions WHERE id=?", (row["id"],)).fetchone()
                if saved is None or dict(saved) != dict(row):
                    raise NetworkError("an affected target changed concurrently; retry the data review")
                if db.execute("SELECT 1 FROM claims WHERE function_id=?", (row["id"],)).fetchone():
                    raise NetworkError("an affected data target is claimed; finish or release that work first")
                snapshots.append({"function": _json_row(saved),
                    "compiler": function_config(latest, saved["name"])["compiler"],
                    "attempts": [_json_row(r) for r in db.execute("SELECT * FROM attempts WHERE function_id=? ORDER BY id", (row["id"],))],
                    "notes": [_json_row(r) for r in db.execute("SELECT * FROM notes WHERE function_id=? ORDER BY id", (row["id"],))],
                    "twin_misses": [_json_row(r) for r in db.execute("SELECT * FROM twin_misses WHERE function_id=?", (row["id"],))],
                    "symbols": [_json_row(r) for r in db.execute("SELECT * FROM symbols WHERE project_id=? AND name=?", (project["id"],row["name"]))]})
            archived_config = latest
            evidence = {"format": 1, "kind": "psx-main-data-review", "token": token,
                "reason": reason.strip(), "original_disc_sha256": layout["sha256"],
                "analysis_sha256": hashlib.sha256(image).hexdigest(), "data_ranges": definitions,
                "original_config": latest, "original_splat": old_text.decode("utf-8"),
                "original_layout": old_layout.decode("utf-8") if old_layout is not None else None, "reviewed_layout": declaration,
                "contexts": [_json_row(r) for r in db.execute("SELECT * FROM context_versions WHERE project_id=?", (project["id"],))],
                "targets": snapshots}
            payload = json.dumps(evidence, sort_keys=True)
            (backup / "review.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            db.execute("CREATE TABLE IF NOT EXISTS psx_data_reviews(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, agent_id INTEGER, created_at REAL NOT NULL, reason TEXT NOT NULL, evidence TEXT NOT NULL)")
            review_id = db.execute("INSERT INTO psx_data_reviews(project_id,agent_id,created_at,reason,evidence) VALUES(?,?,?,?,?)",
                (project["id"], agent.id, time.time(), reason.strip(), payload)).lastrowid
            updated = json.loads(json.dumps(latest))
            updated["psx_disc"] = layout
            updated["psx_modules"] = psx_data.merge_facts(updated.get("psx_modules", {}), {"main": {"data_ranges": definitions}})
            updated["psx_layout"] = hashlib.sha256(json.dumps(declaration, sort_keys=True).encode()).hexdigest()
            for row in affected:
                for table in ("attempts", "notes", "twin_misses"):
                    db.execute(f"DELETE FROM {table} WHERE function_id=?", (row["id"],))
                db.execute("DELETE FROM functions WHERE id=?", (row["id"],))
                db.execute("INSERT INTO symbols(project_id,name,address,size,kind) VALUES(?,?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET kind='data'",
                    (project["id"], row["name"], row["vram"], row["size"], "data"))
                updated.get("function_compilers", {}).pop(row["name"], None)
            _write(config_path, new_text)
            wrote_config = True
            _write(layout_path, (json.dumps(declaration, indent=2) + "\n").encode("utf-8"))
            wrote_layout = True
            db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(updated), project["id"]))
            net._event(db, project["id"], agent.id, "data-review", f"review {review_id}: {len(affected)} archived targets: {reason.strip()}")
    except BaseException:
        if wrote_config:
            _write(config_path, old_text)
        if wrote_layout:
            if old_layout is None:
                layout_path.unlink(missing_ok=True)
            else:
                _write(layout_path, old_layout)
        raise
    for cache in (net._syms, net._xrefs, net._ops):
        cache.pop(project["id"], None)
    for key in list(net._diffs):
        if key[0] in ids:
            net._diffs.pop(key, None)
    net.twins.forget(project)
    transferred = _transfer(net, slug, agent, affected, archived_config) if transfer else []
    return {"project": slug, "review": review_id, "archived": [row["name"] for row in affected],
            "evidence": str(backup / "review.json"), "transferred": transferred}


def _transfer(net, slug, agent, archived, cfg):
    from ..app.twins import apply
    from .psx_modules import profile
    project = net.project_row(slug)
    donors = {}
    for row in archived:
        if row["matched_source"]:
            donors.setdefault(row["target"], []).append(row)
    result = []
    for recipient in net.store.all("SELECT * FROM functions WHERE project_id=? AND unit!='main' AND status='open'", project["id"]):
        choices = donors.get(recipient["target"], [])[:6]
        if not choices or not net.permuter._hold(agent, recipient):
            continue
        try:
            fn = net.store.one("SELECT * FROM functions WHERE id=?", recipient["id"])
            if fn["status"] != "open":
                continue
            context = net._context(project["id"], fn["unit"])
            for donor in choices:
                selected = profile(function_config(cfg, donor["name"])["compiler"], {})
                source = apply(donor["matched_source"], {donor["name"]: fn["name"]})
                current = net.project_row(slug)
                config = net.cfg(current)
                config["function_compilers"] = {**config.get("function_compilers", {}), fn["name"]: selected}
                candidate = dict(current, config=json.dumps(config))
                built = net._compile(candidate, context["header"], source, fn)
                if not built.ok:
                    continue
                obj, exact, _ = net._evaluate(fn, candidate, built.obj)
                if obj is None or exact is not True:
                    continue
                net.set_function_compiler(slug, fn["name"], selected)
                net._record(fn, agent, 0, source, context["version"], matched=True)
                result.append(fn["name"])
                break
        finally:
            net.permuter._let_go(agent, recipient)
    return result
