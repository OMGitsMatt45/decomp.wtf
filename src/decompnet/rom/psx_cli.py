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
    build.add_argument("--mod", action="store_true", help="build changed C/C++ within original function/file limits")
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
