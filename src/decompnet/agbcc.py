"""The three agbcc build stages, without requiring a Unix shell on Windows."""

from __future__ import annotations

import argparse
import subprocess


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp", required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--as", dest="assembler", required=True)
    parser.add_argument("--builtin-include", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--obj", required=True)
    parser.add_argument("--include", required=True)
    args, flags = parser.parse_known_args(argv)
    if flags[:1] == ["--"]:
        flags = flags[1:]
    commands = [
        [args.cpp, "-nostdinc", "-undef", "-I", args.builtin_include, "-I", args.include, args.src,
         "-o", args.obj + ".i"],
        [args.cc, *flags, args.obj + ".i", "-o", args.obj + ".s"],
        [args.assembler, "-mcpu=arm7tdmi", "-o", args.obj, args.obj + ".s"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command)
        except OSError as e:
            parser.exit(1, f"couldn't start {command[0]}: {e}\n")
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
