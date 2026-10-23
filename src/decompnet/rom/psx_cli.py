"""PS1 disc inventory, local import and exact reconstructable exports."""

import json
import sys
from pathlib import Path

from ..network import NetworkError


def add_parser(subparsers):
    parser = subparsers.add_parser("psx", help="PlayStation 1 programs and full-disc matching projects")
    sub = parser.add_subparsers(dest="psx_cmd", required=True)
    inspect = sub.add_parser("inspect", help="inventory disc files, discovered overlays and rebuild coverage")
    load = sub.add_parser("import", help="import your PS1 executable or disc")
    export = sub.add_parser("export", help="export and verify a matching PS1 project")
    for command in (inspect, load):
        command.add_argument("rom", type=Path)
    load.add_argument("--own-copy", required=True, action="store_true")
    load.add_argument("--toolchain", choices=("gcc-2.7.2-psx", "gcc-2.8.1-psx"))
    export.add_argument("project")
    for command in (load, export):
        command.add_argument("--workspace", required=True, type=Path)


def run(args):
    try:
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
                                      log=lambda message: print(message, file=sys.stderr))
                result = {"project": slug, "root": net.project_row(slug)["root"], "disc": net.overview(slug)["disc"]}
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
