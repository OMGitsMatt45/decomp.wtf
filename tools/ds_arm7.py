"""Inspect DS modules, or verify an isolated ARM7 C/C++ function, without a BIOS."""

import argparse
import json
from pathlib import Path

from decompnet.rom.ds_arm7 import draft, verify
from decompnet.rom.nds_modules import NdsImage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    check = sub.add_parser("verify")
    make_draft = sub.add_parser("draft")
    for command in (check, make_draft):
        command.add_argument("--module", default="arm7")
        command.add_argument("--address", type=lambda s: int(s, 0), required=True)
        command.add_argument("--size", type=lambda s: int(s, 0), required=True)
        command.add_argument("--mode", choices=("arm", "thumb"), required=True)
        command.add_argument("--symbol", required=True)
    check.add_argument("--source", type=Path, required=True)
    check.add_argument("--language", choices=("c", "c++"), default="c")
    check.add_argument("--compiler", default="2.0/sp1p5")
    args = parser.parse_args()
    try:
        image = NdsImage.read(args.rom)
        if args.command == "draft":
            print(draft(image, args.module, args.address, args.size, args.mode, args.symbol), end="")
            return 0
        result = image.inspect() if args.command == "inspect" else verify(
            image, args.module, args.address, args.size, args.mode,
            args.source.read_text(encoding="utf-8"), args.symbol,
            language=args.language, version=args.compiler)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, indent=2))
    return 0 if args.command == "inspect" or result["exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
