"""One source project and build for an explicitly ordered set of PS1 discs."""

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from ..limits import capped
from ..network import NetworkError


def member(net, slug):
    proj = net.project_row(slug)
    cfg = net.cfg(proj)
    disc = cfg.get("psx_disc") or {}
    if cfg.get("platform") != "psx" or not disc.get("supported"):
        raise NetworkError(f"{slug}: choose an imported PS1 disc with complete-image reconstruction")
    return proj, cfg


def configure(net, slug, projects, title=""):
    """Group existing per-disc targets without merging their identities or claims."""
    _, current = member(net, slug)
    if projects is None:
        previous = current.get("psx_disc_set")
        if previous:
            with net.store.tx() as db:
                for item in previous["discs"]:
                    row = db.execute("SELECT id,config FROM projects WHERE slug=?", (item["slug"],)).fetchone()
                    if row:
                        cfg = json.loads(row["config"])
                        if cfg.get("psx_disc_set", {}).get("id") == previous["id"]:
                            cfg.pop("psx_disc_set", None)
                            cfg.pop("export", None)
                            db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), row["id"]))
        return None
    if not isinstance(projects, list) or not 2 <= len(projects) <= 16 or any(not isinstance(p, str) for p in projects):
        raise NetworkError("choose 2 to 16 PS1 disc projects in disc order")
    if len(set(projects)) != len(projects) or slug not in projects:
        raise NetworkError("disc projects must be distinct and include the current project")
    if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(c in title for c in "\0\r\n"):
        raise NetworkError("give the combined game a single-line title of 1 to 200 characters")
    rows = [member(net, p) for p in projects]
    discs = [{"slug": p["slug"], "sha256": cfg["psx_disc"].get("identity", cfg["psx_disc"]["sha256"])} for p, cfg in rows]
    if len({d["sha256"] for d in discs}) != len(discs):
        raise NetworkError("the same disc image cannot appear twice in a game")
    identity = hashlib.sha256(json.dumps(discs, sort_keys=True).encode()).hexdigest()
    meta = {"format": 1, "id": identity, "title": title.strip(), "discs": discs}
    with net.store.tx() as db:
        for proj, _ in rows:
            cfg = json.loads(db.execute("SELECT config FROM projects WHERE id=?", (proj["id"],)).fetchone()["config"])
            existing = cfg.get("psx_disc_set")
            if existing and existing["id"] != identity:
                raise NetworkError(f"{proj['slug']} belongs to another game; ungroup it before changing discs or order")
            cfg["psx_disc_set"] = meta
            cfg.pop("export", None)
            db.execute("UPDATE projects SET config=? WHERE id=?", (json.dumps(cfg), proj["id"]))
    return meta


def members(net, meta):
    if meta.get("format") != 1 or not 2 <= len(meta.get("discs", [])) <= 16:
        raise NetworkError("invalid PS1 disc-set configuration")
    rows = []
    for item in meta["discs"]:
        proj, cfg = member(net, item["slug"])
        if cfg.get("psx_disc_set") != meta or cfg["psx_disc"].get("identity", cfg["psx_disc"]["sha256"]) != item["sha256"]:
            raise NetworkError(f"{item['slug']}: disc identity or combined-game membership changed")
        rows.append((proj, cfg))
    return rows


def share_sources(out, projects):
    """Share identical authored source text; each disc still compiles and judges it."""
    found = defaultdict(list)
    manifests = []
    for folder in projects:
        root = out / folder
        build = json.loads((root / "build.json").read_text(encoding="utf-8"))
        manifests.append((root, build, json.loads((root / "objdiff.json").read_text(encoding="utf-8"))))
        for fn in build["functions"]:
            if source := fn.get("source"):
                path = root / source
                found[(path.suffix, path.read_bytes())].append((root, fn, path))
    shared = []
    for (extension, data), owners in found.items():
        if len({root for root, _, _ in owners}) < 2:
            continue
        name = hashlib.sha256(data).hexdigest() + extension
        target = out / "shared" / "src" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        uses = []
        for root, fn, path in owners:
            old = fn["source"]
            fn["source"] = "../../shared/src/" + name
            path.unlink(missing_ok=True)
            obj = next(obj for folder, _, obj in manifests if folder == root)
            for unit in obj["units"]:
                if unit.get("metadata", {}).get("source_path") == old:
                    unit["metadata"]["source_path"] = fn["source"]
                    unit["base_path"] = "build/shared/" + hashlib.sha256(fn["source"].encode()).hexdigest() + ".o"
            uses.append({"disc": root.name, "function": fn["name"]})
        shared.append({"source": target.relative_to(out).as_posix(), "uses": uses})
    for root, build, obj in manifests:
        (root / "build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")
        (root / "objdiff.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return shared


def package(out, log=print):
    """One private, atomic ZIP: sources, pinned inputs, and verified outputs."""
    archive = out.with_suffix(".zip")
    temporary = archive.with_suffix(".zip.tmp")
    archive.unlink(missing_ok=True)
    temporary.unlink(missing_ok=True)
    log("packaging the combined source project and verified discs")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zipped:
            for path in sorted(out.rglob("*")):
                rel = path.relative_to(out)
                if path.is_symlink():
                    raise NetworkError("the combined export contains a symbolic link")
                if not path.is_file() or any(p in (".git", "__pycache__", ".splat") for p in rel.parts):
                    continue
                # Child objects and duplicate child disc outputs regenerate;
                # the root build directory contains each qualified disc once.
                if rel.parts[0] == "discs" and "build" in rel.parts:
                    continue
                zipped.write(path, (Path(out.name) / rel).as_posix())
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def export_set(net, slug, out=None, log=print):
    from .export import export_rom

    _, cfg = member(net, slug)
    meta = cfg["psx_disc_set"]
    rows = members(net, meta)
    out = Path(rows[0][0]["root"]) / "source-set"
    out.with_suffix(".zip").unlink(missing_ok=True)
    if out.exists():
        for child in out.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    results, discs = [], []
    for number, (proj, cfg) in enumerate(rows, 1):
        folder = f"discs/disc-{number}"
        log(f"exporting {meta['title']}, disc {number} of {len(rows)}")
        result = export_rom(net, proj["slug"], out / folder, log=log)
        results.append(result)
        if not result["identical"] or result.get("scope") != "disc":
            raise NetworkError(f"disc {number} failed its original-image reconstruction: {result.get('log', '')[-1500:]}")
        description = json.loads((out / folder / "build.json").read_text(encoding="utf-8"))
        child = description["disc"]
        ext = Path(child["output"]).suffix
        disc = {"project": folder, "output": f"build/disc-{number}{ext}",
                "sha256": cfg["psx_disc"]["sha256"], "original_size": cfg["psx_disc"]["original_size"]}
        if artifacts := child.get("artifacts"):
            disc["artifacts"] = [{**a, "child": a["output"], "output": f"build/disc-{number}/" +
                (a["output"].removeprefix("build/disc-media/") if "companions_output" in child else Path(a["output"]).name)}
                for a in artifacts]
            disc["output"] = disc["artifacts"][0]["output"]
        discs.append(disc)
    shared = share_sources(out, [d["project"] for d in discs])
    build = {"format": 1, "title": meta["title"], "discs": discs, "shared": shared}
    (out / "disc-set.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("psx_set_build.py"), out / "build.py")
    units = []
    for disc in discs:
        obj = json.loads((out / disc["project"] / "objdiff.json").read_text(encoding="utf-8"))
        for unit in obj["units"]:
            unit["name"] = Path(disc["project"]).name + "/" + unit["name"]
            for field in ("target_path", "base_path"):
                if unit.get(field):
                    unit[field] = disc["project"] + "/" + unit[field]
            if source := unit.get("metadata", {}).get("source_path"):
                unit["metadata"]["source_path"] = (out / disc["project"] / source).resolve().relative_to(out.resolve()).as_posix()
            units.append(unit)
    (out / "objdiff.json").write_text(json.dumps({"build_base": False, "build_target": False, "units": units}, indent=2), encoding="utf-8")
    (out / ".gitignore").write_text("build/\n**/build/\n**/baserom*\n**/asm/\n**/assets/\n**/*.ld\n**/*_auto.txt\n**/.splat/\n**/*.d\n", encoding="utf-8")
    (out / ".gitattributes").write_text("*.c text eol=lf\n*.cpp text eol=lf\n*.h text eol=lf\n*.hpp text eol=lf\n", encoding="utf-8")
    (out / "README.md").write_text(f"# {meta['title']}\n\nOne PS1 source project for {len(discs)} discs. "
        "Run `python build.py` to build and verify every disc together. Outputs are listed in `disc-set.json`. "
        "`shared/src/` contains identical recovered source files reused by several discs. Each disc compiles "
        "and checks that source against its own addresses, headers, compiler settings and original image. "
        "Disc-specific code and assets remain under `discs/disc-N/`. Keep each original disc at the private "
        "baserom path described in its directory's README. Generated assembly, assets and objects can be deleted "
        "before a clean build. Any failure removes all previous combined disc outputs.\n\n"
        "Run `python build.py mod` after editing C/C++ to build all discs together under `build/mod/`. "
        "Each disc first verifies its original assembly baseline. Changed functions must fit their original "
        "slots and cannot add owned data, BSS or helpers. The child READMEs describe these limits. "
        "`build/mod/disc-set-result.json` records the changed functions and output hashes; a failed disc "
        "removes all combined mod outputs.\n\n"
        "This builds the original separate disc images for normal emulator disc swapping. "
        "It does not merge filesystems or remove game disc-change behavior.\n", encoding="utf-8")
    proc = subprocess.run(capped([sys.executable, "build.py"]), cwd=out, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=3600)
    archive = package(out, log) if proc.returncode == 0 else None
    return {"path": str(out), "identical": proc.returncode == 0, "scope": "disc-set", "format": "matching",
            "matched": sum(r["matched"] for r in results), "functions": sum(r["functions"] for r in results),
            "language": results[0]["language"], "fallback": [f for r in results for f in r["fallback"]],
            "discs": discs, "disc_set_id": meta["id"], "shared_sources": len(shared), "archive": str(archive) if archive else None,
            "log": (proc.stdout + proc.stderr)[-3000:]}
