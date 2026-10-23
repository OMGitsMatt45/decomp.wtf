"""N64 import, reviewed layouts and cartridge exports using the local app database."""

import json
import sys
from pathlib import Path

from ..network import NetworkError


def add_parser(subparsers):
    parser = subparsers.add_parser("n64", help="Nintendo 64 layouts and rebuildable projects")
    sub = parser.add_subparsers(dest="n64_cmd", required=True)
    inspect = sub.add_parser("inspect", help="validate a reviewed module layout against a cartridge")
    load = sub.add_parser("import", help="import your cartridge into a local workspace")
    export = sub.add_parser("export", help="export a complete matching or shiftable N64 project")
    profile = sub.add_parser("profile", help="select a compiler profile for one function")
    profile.add_argument("project")
    profile.add_argument("function")
    profile.add_argument("--toolchain")
    profile.add_argument("--optimization", choices=("O0", "O1", "O2"))
    profile.add_argument("--frontend", choices=("edg", "cfront"))
    profile.add_argument("--language", choices=("c", "c++"))
    profile.add_argument("--reset", action="store_true")
    for command in (inspect, load):
        command.add_argument("rom", type=Path)
        command.add_argument("--layout", type=Path, required=command is inspect)
    load.add_argument("--own-copy", required=True, action="store_true")
    load.add_argument("--toolchain")
    load.add_argument("--optimization", choices=("O0", "O1", "O2"), help="override the named toolchain's optimization profile")
    export.add_argument("project")
    export.add_argument("--format", choices=("matching", "shiftable"), default="matching")
    for command in (load, export, profile):
        command.add_argument("--workspace", required=True, type=Path)


def run(args):
    try:
        if args.n64_cmd == "inspect":
            from .n64 import read_info
            from .n64_layout import reviewed
            original, _ = read_info(args.rom.read_bytes())
            segments, _, context = reviewed(original, json.loads(args.layout.read_text(encoding="utf-8")))
            result = {"sha256": context["sha256"], "original_size": context["original_size"],
                      "segments": segments, "compressed_modules": len(context["blocks"])}
        else:
            from ..app.engine import RomNetwork
            net = RomNetwork(args.db, args.workspace)
            if args.n64_cmd == "import":
                from .n64 import read_info
                read_info(args.rom.read_bytes())
                layout = json.loads(args.layout.read_text(encoding="utf-8")) if args.layout else None
                flags = None
                if args.optimization is not None:
                    from .. import toolchains
                    if args.toolchain not in ("ido-5.3", "ido-7.1", "gcc-2.7.2-kmc"):
                        raise ValueError("--optimization needs --toolchain ido-5.3, ido-7.1 or gcc-2.7.2-kmc")
                    flags = ["-" + args.optimization, *[f for f in toolchains.get(args.toolchain).flags if not f.startswith("-O")]]
                slug = net.import_rom(args.rom, toolchain=args.toolchain, flags=flags, confirmed=args.own_copy,
                                      reviewed_layout=layout, log=lambda message: print(message, file=sys.stderr))
                result = {"project": slug, "root": net.project_row(slug)["root"]}
            elif args.n64_cmd == "profile":
                from ..project import function_config
                from .n64_profiles import profile, optimization
                fn = net._function(args.function, args.project)
                cfg = net.cfg(net.project_row(args.project))
                current = function_config(cfg, fn["name"])["compiler"]
                override = {key: value for key, value in (("toolchain", args.toolchain),
                    ("cpp_frontend", args.frontend), ("language", args.language)) if value is not None}
                selected = profile(current, override)
                if args.optimization:
                    selected = optimization(selected, args.optimization)
                result = net.set_function_compiler(args.project, fn["name"], None if args.reset else selected)
            else:
                if net.cfg(net.project_row(args.project)).get("platform") != "n64":
                    raise ValueError("choose an N64 cartridge project")
                result = net.export_rom(args.project, format=args.format, log=lambda message: print(message, file=sys.stderr))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, NetworkError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
