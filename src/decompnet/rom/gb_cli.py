"""Local assembly tools, kept separate from the application's C/C++ claim workflow."""

import json
import sys
from pathlib import Path

from . import gb


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("gb", help="Game Boy / Game Boy Color assembly workbench")
    sub = parser.add_subparsers(dest="gb_cmd", required=True)
    inspect = sub.add_parser("inspect", help="inspect a cartridge and find direct control flow")
    export = sub.add_parser("export", help="create an editable RGBDS project with exact rebuild verification")
    for command in (inspect, export):
        command.add_argument("rom", type=Path)
        command.add_argument("--entry", type=gb.Address.parse, action="append", default=[], metavar="BANK:ADDR",
                             help="extra code entry in hexadecimal, e.g. 02:4000 (entry 00:0100 is always included)")
        command.add_argument("--no-discover", action="store_true", help="skip automatic code discovery")
    export.add_argument("out", type=Path)
    export.add_argument("--range", type=gb.CodeRange.parse, action="append", default=[], dest="ranges",
                        metavar="BANK:START:END", help="extra code range, hexadecimal end exclusive")


def run(args) -> int:
    try:
        raw = args.rom.read_bytes()
        if args.no_discover and args.entry:
            raise gb.CartridgeError("--no-discover cannot be combined with --entry")
        entries = [] if args.no_discover else [gb.Address(0, 0x100), *args.entry]
        if args.gb_cmd == "inspect":
            info = gb.read_info(raw)
            regions, notes = gb.discover(raw, entries)
            result = {"rom": info, "code_ranges": [r.to_dict() for r in regions],
                      "assembly_bytes": sum(r.size for r in regions), "analysis_notes": notes}
        else:
            from .export_gb import export
            result = export(raw, args.out, entries=entries, ranges=args.ranges)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
