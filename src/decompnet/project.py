"""Project definitions (project.toml) and importing target functions into the network."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import time
import tomllib
from pathlib import Path

from . import cpp, scoring, seeds, toolchains, wsl
from .compiler import CompilerConfig, compile_source
from .elfobj import extract_function, list_functions
from .store import Store


# A project may only be imported with a declared lawful basis for sharing its code.
LEGAL_BASES = {
    "own-code": "written by the person or team importing it",
    "open-source": "released by its authors under an open license",
    "homebrew": "homebrew whose author allows decompilation and sharing",
    "permission": "imported with written permission from the rights holder",
}


class ProjectRejected(ValueError):
    pass


def check_legal(cfg: dict) -> dict:
    """Refuse projects without a lawful basis. This is policy, not paperwork: the network only
    hosts code that may legally be shared (no commercial games without the rights holder's OK)."""
    legal = cfg.get("legal") or {}
    basis = legal.get("basis")
    if basis not in LEGAL_BASES:
        raise ProjectRejected(
            "project.toml needs a [legal] section with basis = one of " + ", ".join(LEGAL_BASES)
            + ". Commercial games can only be imported with the rights holder's permission.")
    if basis != "own-code" and not str(legal.get("evidence", "")).strip():
        raise ProjectRejected(f"basis '{basis}' needs legal.evidence: a link to the license, "
                              "the author's statement, or a reference to the written permission")
    if not str(legal.get("license", "")).strip():
        raise ProjectRejected("legal.license must name the license contributions are shared under (e.g. CC0-1.0)")
    return legal


def load_config(root: Path) -> dict:
    with open(root / "project.toml", "rb") as f:
        return tomllib.load(f)


def compiler_config(root: Path, cfg: dict) -> CompilerConfig:
    """Build the sandboxed compile command for a project.

    Either `cmd` (a full command with {src} {obj} {include} placeholders) or `toolchain` (a registry id,
    see toolchains.toml) plus optional `flags`. With a toolchain, `{tc}` expands to its install directory,
    which is mounted read-only into the sandbox together with any runtime it requires."""
    c = cfg["compiler"]
    language = cpp.language(cfg)
    ro_paths = [str((root / p).resolve()) for p in c.get("ro_paths", [])]
    runtime32 = None
    linux = False
    relative_paths = False
    if "toolchain" in c:
        tc = toolchains.get(c["toolchain"])
        if why := tc.unsupported_reason:
            raise toolchains.ToolchainError(why)
        linux = tc.via_wsl  # Windows: a Linux toolchain, run inside WSL 2
        if linux and not (ok := wsl.status())[0]:
            raise toolchains.ToolchainError(f"{tc.name} is a Linux program: on Windows it runs in WSL 2. {ok[1]}")
        dirs = toolchains.runtime_dirs(tc.id)
        tc_dir = wsl.path(dirs[0]) if linux else dirs[0].as_posix()
        ro_paths += [str(d) for d in dirs]
        if "runtime-i386" in tc.dependencies(linux) and not linux:  # WSL programs bring the runtime themselves
            runtime32 = str(toolchains.require("runtime-i386"))
        flags = c.get("flags", tc.flags)
        windows = not linux and toolchains.current_platform().startswith("windows-")
        relative_paths = windows and tc.id in ("ido-5.3", "ido-7.1")
        template = tc.windows_cmd if windows and tc.windows_cmd is not None else tc.cmd
        cc = tc.windows_cc if windows and tc.windows_cc is not None else tc.cc
        if c.get("cmd"):
            base = c["cmd"]
        elif template:  # a full template ({flags} expands to the flags)
            base = [x for a in template for x in (flags if a == "{flags}" else [a])]
        else:
            base = [*cc, *flags, "-I{include}", "{src}", "-o", "{obj}"]
        cmd = [a.replace("{tc}", tc_dir).replace("{python}", sys.executable) for a in base]
        if language == "c++" and not c.get("cmd"):
            suffix = ".exe" if windows else ""
            if tc.id == "gcc-2.7.2-kmc":
                if not (dirs[0] / f"cc1plus{suffix}").is_file():
                    raise toolchains.ToolchainError("The N64 C++ frontend is missing: rerun setup or `decompnet toolchain install gcc-2.7.2-kmc --force`")
                cmd[1:1] = ["-x", "c++", "-fno-handle-exceptions", "-fno-rtti"]
            elif tc.id == "ido-7.1":
                if not all((dirs[0] / f"{name}{suffix}").is_file() for name in ("NCC", "edgcpfe")):
                    raise toolchains.ToolchainError("The IDO 7.1 C++ frontend is missing: reinstall with `decompnet toolchain install ido-7.1 --force --accept-license`")
                cmd[0] = f"{tc_dir}/NCC"
            elif tc.id == "ido-5.3":
                raise toolchains.ToolchainError("IDO 5.3's pinned native package has no C++ frontend (cfront). Keep compiler.language = 'c'; IDO 7.1 uses a different frontend and is not a compatible substitute for matching.")
            else:
                raise toolchains.ToolchainError(f"{tc.name} has no verified C++ setup")
        for dep in tc.dependencies(linux):  # {tc:<id>} is another toolchain this one needs
            where = toolchains.path(dep, linux)
            cmd = [a.replace(f"{{tc:{dep}}}", wsl.path(where) if linux else where.as_posix()) for a in cmd]
        if windows and cmd and Path(cmd[0] + ".exe").is_file():
            cmd[0] += ".exe"
    else:
        cmd = list(c["cmd"])
    return CompilerConfig(
        cmd=cmd,
        language=language,
        c_linkage=language == "c++" and cfg.get("kind") == "rom",
        relative_paths=relative_paths,
        timeout=float(c.get("timeout", 15)),
        sandbox=c.get("sandbox", "auto"),
        image=c.get("image"),
        ro_paths=tuple(ro_paths),
        include_dirs=tuple(str((root / p).resolve()) for p in c.get("include_dirs", [])),
        runtime32=runtime32,
        wsl=linux,
    )


def target_objects(root: Path, cfg: dict) -> list[Path]:
    t = cfg["target"]
    if isinstance(t.get("build_from"), list):  # one object per source file, named after it
        return [root / "target" / f"{Path(src).stem}.o" for src in t["build_from"]]
    return [root / o for o in t["objects"]]


def build_target(root: Path, cfg: dict, log=print) -> None:
    """Build target objects from source the project is allowed to have (own code / open source),
    using the project's own sandboxed toolchain. Real ROM projects ship assembled targets instead."""
    t = cfg["target"]
    sources = t["build_from"] if isinstance(t["build_from"], list) else [t["build_from"]]
    outputs = target_objects(root, cfg)
    for src, out in zip(sources, outputs):
        cc = compiler_config(root, cfg)
        src_path = root / src
        cc.include_dirs = (*cc.include_dirs, str(src_path.parent))
        log(f"building {out.relative_to(root)} from {src} with {cfg['compiler'].get('toolchain', 'cmd')}")
        res = compile_source(cc, "", src_path.read_text(errors="replace", encoding="utf-8"), trusted=True)
        if not res.ok:
            raise ProjectRejected(f"target build failed for {src}:\n{res.log}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(res.obj)


def import_project(store: Store, root: Path, log=print) -> int:
    """Create or refresh a project. Existing progress (matches, attempts) is kept;
    new functions are added; targets of unmatched functions are refreshed."""
    root = root.resolve()
    cfg = load_config(root)
    check_legal(cfg)
    slug = cfg["slug"]
    target = cfg["target"]

    objects = target_objects(root, cfg)
    hash_only = target.get("verification", "full") == "hash"
    if "build_from" in target and not all(o.exists() for o in objects):
        build_target(root, cfg, log)
    elif "build" in target and not all(o.exists() for o in objects):
        log(f"building target objects: {' '.join(target['build'])}")
        subprocess.run(target["build"], cwd=root, check=True)

    funcs = []
    seen: dict[str, str] = {}
    arch, big_endian = None, False
    for obj in objects:
        data = obj.read_bytes()
        for name in list_functions(data):
            if name in cfg.get("exclude", []):
                continue
            if name in seen:
                raise ProjectRejected(f"function {name!r} exists in both {seen[name]} and {obj.name}; "
                                      f"add one of them to `exclude` in project.toml")
            seen[name] = obj.name
            unit = obj.stem
            fn = extract_function(data, name)
            arch, big_endian = fn.arch, fn.big_endian
            insns = scoring.disassemble(fn)
            seed_file = root / "seeds" / f"{name}.c"
            funcs.append([name, fn, len(insns), scoring.asm_text(fn),
                          seed_file.read_text(encoding="utf-8") if seed_file.exists() else None, unit])

    header = (root / cfg["context"]["file"]).read_text(encoding="utf-8")
    # Optional per-unit headers: [context] units = "units/{unit}.h" (one per source file / object)
    unit_headers = {}
    if cfg["context"].get("units"):
        for obj in objects:
            path = root / cfg["context"]["units"].format(unit=obj.stem)
            if path.exists():
                unit_headers[obj.stem] = path.read_text(encoding="utf-8")
    header_of = lambda f: unit_headers.get(f[5], header)
    # Functions without a hand-written seed get a machine-generated starting point (m2c), when available.
    tc_id = cfg["compiler"].get("toolchain")
    missing = [f for f in funcs if f[4] is None]
    if missing and not hash_only and tc_id in seeds.M2C_TARGETS and seeds.available():
        with ThreadPoolExecutor(max_workers=4) as pool:
            drafts = list(pool.map(lambda f: seeds.generate(f[1], tc_id, header_of(f)), missing))
        for f, draft in zip(missing, drafts):
            f[4] = f"/* machine-generated by m2c: a starting point, not a match */\n{draft}" if draft else None
        log(f"m2c drafted {sum(d is not None for d in drafts)}/{len(missing)} functions")
    now = time.time()
    with store.tx() as db:
        row = db.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if row is None:
            pid = db.execute(
                "INSERT INTO projects(slug,name,description,arch,big_endian,root,config) VALUES(?,?,?,?,?,?,?)",
                (slug, cfg.get("name", slug), cfg.get("description", ""), arch, big_endian, str(root), json.dumps(cfg)),
            ).lastrowid
            db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                       "VALUES(?,?,?,?,?,?,?)", (pid, 1, header, None, "initial import", now, ""))
        else:
            pid = row["id"]
            db.execute(
                "UPDATE projects SET name=?,description=?,arch=?,big_endian=?,root=?,config=? WHERE id=?",
                (cfg.get("name", slug), cfg.get("description", ""), arch, big_endian, str(root), json.dumps(cfg), pid),
            )
        have = {r["unit"] for r in db.execute("SELECT DISTINCT unit FROM context_versions WHERE project_id=?", (pid,))}
        for unit, text in unit_headers.items():
            if unit not in have:
                version = db.execute("SELECT MAX(version) AS v FROM context_versions WHERE project_id=?", (pid,)).fetchone()["v"] + 1
                db.execute("INSERT INTO context_versions(project_id,version,header,agent_id,message,created_at,unit) "
                           "VALUES(?,?,?,?,?,?,?)", (pid, version, text, None, f"initial import ({unit})", now, unit))
        for name, fn, n_insns, asm, seed, unit in funcs:
            if hash_only:  # keep only a one-way fingerprint and the size, never the code or its disassembly
                target_bytes, relocs, asm, seed = None, "[]", "", None
            else:
                target_bytes, relocs = fn.code, json.dumps([r.to_json() for r in fn.relocs])
            db.execute(
                """INSERT INTO functions(project_id,name,size,n_insns,target,relocs,asm,seed,fingerprint,unit)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(project_id,name) DO UPDATE SET size=excluded.size, n_insns=excluded.n_insns,
                   target=excluded.target, relocs=excluded.relocs, asm=excluded.asm, seed=excluded.seed,
                   fingerprint=excluded.fingerprint, unit=excluded.unit
                   WHERE functions.status != 'matched'""",
                (pid, name, len(fn.code), n_insns, target_bytes, relocs, asm, seed, fn.fingerprint(), unit),
            )
    log(f"project {slug!r}: {len(funcs)} functions ({arch})")
    return pid
