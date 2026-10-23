"""PS1 disc inventory, local import and exact reconstructable exports."""

import json
import subprocess
import sys
from pathlib import Path

from ..network import NetworkError


def add_parser(subparsers):
    parser = subparsers.add_parser("psx", help="PlayStation 1 programs and full-disc matching projects")
    sub = parser.add_subparsers(dest="psx_cmd", required=True)
    inspect = sub.add_parser("inspect", help="inventory disc files, discovered overlays and rebuild coverage")
    load = sub.add_parser("import", help="import your PS1 executable or disc")
    export = sub.add_parser("export", help="export and verify a matching PS1 project")
    build = sub.add_parser("build", help="rebuild an exported PS1 source project")
    build.add_argument("directory", type=Path)
    build.add_argument("--mod", action="store_true", help="build changed C/C++ and reviewed resource replacements")
    upgrade = sub.add_parser("upgrade", help="update exported build helpers, keeping sources and helper backups")
    upgrade.add_argument("directory", type=Path)
    reserve = sub.add_parser("reserve", help="record reviewed unused loaded space for larger source changes")
    reserve.add_argument("directory", type=Path, help="exported disc project; use discs/disc-N for a combined game")
    reserve.add_argument("--module", required=True)
    reserve.add_argument("--start", required=True, type=lambda v: int(v, 0), help="loaded RAM address, for example 0x80010600")
    reserve.add_argument("--size", required=True, type=lambda v: int(v, 0))
    combine = sub.add_parser("combine", help="combine disc projects into one game source project and build")
    combine.add_argument("projects", nargs="+", help="existing project slugs in disc order")
    combine.add_argument("--title", required=True)
    ungroup = sub.add_parser("ungroup", help="restore independent exports for a combined game's discs")
    ungroup.add_argument("project")
    profile = sub.add_parser("profile", help="select one function's period compiler and C/C++ language")
    profile.add_argument("project")
    profile.add_argument("function")
    profile.add_argument("--toolchain", choices=("gcc-2.7.2-psx", "gcc-2.8.1-psx"))
    profile.add_argument("--language", choices=("c", "c++"))
    profile.add_argument("--optimization", choices=("O0", "O1", "O2"))
    profile.add_argument("--reset", action="store_true")
    recover = sub.add_parser("recover", help="recover and verify C/C++ locally without an AI agent")
    recover.add_argument("project")
    recover.add_argument("--workspace", required=True, type=Path)
    recover.add_argument("--limit", type=int, default=0, help="maximum attempted functions; 0 means all")
    recover.add_argument("--max-insns", type=int, default=0)
    recover.add_argument("--leaves-only", action="store_true", help="try deterministic integer/memory leaves without m2c")
    recover.add_argument("--search-profiles", action="store_true", help="try installed PS1 GCC versions at O0/O1/O2; save only exact matching profiles")
    extract = sub.add_parser("extract", help="extract a resource from an exported disc project")
    replace = sub.add_parser("replace", help="stage an edited resource for the next mod build")
    for command in (extract, replace):
        command.add_argument("directory", type=Path)
        command.add_argument("--file", required=True)
    extract.add_argument("--output", required=True, type=Path)
    replace.add_argument("--input", required=True, type=Path)
    replace.add_argument("--relocate", action="store_true", help="reviewed ISO addressing: append larger files and update directory extents")
    replace.add_argument("--references", type=Path, help="reviewed loader LBA/size/sector-count fields as JSON")
    archive = sub.add_parser("archive", help="inspect and edit Heartbeat HBD resource archives")
    operations = archive.add_subparsers(dest="archive_cmd", required=True)
    for operation in ("inspect", "extract", "replace"):
        command = operations.add_parser(operation)
        command.add_argument("input_path", type=Path, help="original ROM for inspect/extract; exported disc directory for replace")
        command.add_argument("--file", required=True)
        if operation == "inspect":
            command.add_argument("--full", action="store_true", help="include every block/member record")
        else:
            command.add_argument("--sector", required=True, type=lambda v: int(v, 0))
            command.add_argument("--member", required=True, type=int)
            command.add_argument("--output" if operation == "extract" else "--input", required=True, type=Path)
            if operation == "extract":
                command.add_argument("--stored", action="store_true")
    for command in (inspect, load):
        command.add_argument("rom", type=Path)
    load.add_argument("--own-copy", required=True, action="store_true")
    load.add_argument("--toolchain", choices=("gcc-2.7.2-psx", "gcc-2.8.1-psx"))
    load.add_argument("--layout", type=Path, help="reviewed hash-bound archive/compressed module layout JSON")
    export.add_argument("project")
    for command in (load, export, combine, ungroup, profile):
        command.add_argument("--workspace", required=True, type=Path)


def run(args):
    try:
        if args.psx_cmd == "upgrade":
            from .psx_upgrade import upgrade
            print(json.dumps(upgrade(args.directory), indent=2))
            return 0
        if args.psx_cmd == "recover":
            from ..app.engine import RomNetwork
            from .psx_recover import recover
            result = recover(RomNetwork(args.db, args.workspace), args.project, limit=args.limit,
                             max_insns=args.max_insns, machine_drafts=not args.leaves_only, search_profiles=args.search_profiles,
                             log=lambda message: print(message, file=sys.stderr))
            print(json.dumps(result, indent=2))
            return 130 if result["interrupted"] else 0
        if args.psx_cmd in ("extract", "replace"):
            from .psx_assets import extract, stage
            result = (extract(args.directory, args.file, args.output) if args.psx_cmd == "extract" else
                      stage(args.directory, args.file, args.input, relocate=args.relocate,
                            references=json.loads(args.references.read_text(encoding="utf-8")) if args.references else None))
            print(json.dumps(result, indent=2))
            return 0
        if args.psx_cmd == "archive":
            from .psx_archive_cli import run
            print(json.dumps(run(args), indent=2))
            return 0
        if args.psx_cmd == "reserve":
            from .psx_space import configure
            print(json.dumps(configure(args.directory, args.module, args.start, args.size), indent=2))
            return 0
        if args.psx_cmd == "build":
            root = args.directory.resolve()
            combined = (root / "disc-set.json").is_file()
            if not combined and json.loads((root / "build.json").read_text(encoding="utf-8")).get("platform") != "psx":
                raise ValueError("choose an exported PS1 source project")
            process = subprocess.run([sys.executable, "build.py", *(["mod"] if args.mod else [])],
                                     cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(process.stdout + process.stderr, end="", file=sys.stderr)
            if process.returncode:
                return 1
            report = "build/mod/disc-set-result.json" if combined else "build/psx-mod-result.json"
            result = json.loads((root / report).read_text(encoding="utf-8")) if args.mod else {"identical": True}
            print(json.dumps(dict(result, path=str(root)), indent=2))
            return 0
        from .detect import identify
        if args.psx_cmd in ("inspect", "import"):
            picked = identify(args.rom)
            if picked.platform != "psx":
                raise ValueError("choose a PlayStation 1 program or disc")
        if args.psx_cmd == "inspect":
            result = {"program": picked.info, "disc": picked.disc,
                      "overlays": [{"name": name, "load": load, "code_at": code_at, "size": len(data)}
                                   for name, data, load, code_at in picked.overlays]}
        else:
            from ..app.engine import RomNetwork
            net = RomNetwork(args.db, args.workspace)
            if args.psx_cmd == "import":
                slug = net.import_rom(args.rom, toolchain=args.toolchain, confirmed=args.own_copy,
                                      reviewed_layout=json.loads(args.layout.read_text(encoding="utf-8")) if args.layout else None,
                                      log=lambda message: print(message, file=sys.stderr))
                result = {"project": slug, "root": net.project_row(slug)["root"], "disc": net.overview(slug)["disc"]}
            elif args.psx_cmd == "profile":
                from ..project import function_config
                current = function_config(net.cfg(net.project_row(args.project)), args.function)["compiler"]
                selected = {k: getattr(args, k) for k in ("toolchain", "language") if getattr(args, k)}
                if args.optimization:
                    selected["flags"] = ["-" + args.optimization, *[f for f in current["flags"] if not f.startswith("-O")]]
                result = net.set_function_compiler(args.project, args.function, None if args.reset else selected)
            elif args.psx_cmd in ("combine", "ungroup"):
                slug = args.projects[0] if args.psx_cmd == "combine" else args.project
                overview = net.set_psx_disc_set(slug, args.projects if args.psx_cmd == "combine" else None,
                                               args.title if args.psx_cmd == "combine" else "")
                result = {"project": slug, "disc_set": overview["disc_set"]}
            else:
                if net.cfg(net.project_row(args.project)).get("platform") != "psx":
                    raise ValueError("choose a PlayStation 1 project")
                result = net.export_rom(args.project, log=lambda message: print(message, file=sys.stderr))
                if not result["identical"]:
                    print(json.dumps(result, indent=2))
                    return 1
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, NetworkError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
