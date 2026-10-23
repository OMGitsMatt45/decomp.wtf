"""Optional period PS1 assembly, using original GCC and pinned maspsx.

The pipeline is a standalone standard-library script so the same command runs
inside the compile sandbox and in native Windows/Linux exported projects.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ASPSX_VERSIONS = ("2.56", "2.86")


def assembler_profile(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"tool", "version"} or value.get("tool") != "maspsx" \
            or value.get("version") not in ASPSX_VERSIONS:
        raise ValueError("PS1 assembler must be null (GNU) or {tool: 'maspsx', version: '2.56' or '2.86'}")
    return {"tool": "maspsx", "version": value["version"]}


def small_data_limit(flags):
    """Resolve GCC's last -G option, including its separate-argument form."""
    result, index = 8, 0
    while index < len(flags):
        flag = flags[index]
        if flag == "-G":
            index += 1
            value = flags[index] if index < len(flags) else ""
        elif flag.startswith("-G"):
            value = flag[2:]
        else:
            index += 1
            continue
        if not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 0x7FFFFFFF:
            raise ValueError("PS1 maspsx needs a nonnegative integer -G value")
        result = int(value)
        index += 1
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcc-command", required=True)
    parser.add_argument("--maspsx", required=True)
    parser.add_argument("--assembler", required=True)
    parser.add_argument("--version", choices=ASPSX_VERSIONS, required=True)
    parser.add_argument("--small-data", type=int, required=True)
    parser.add_argument("--obj", required=True)
    args = parser.parse_args(argv)
    try:
        command = json.loads(args.gcc_command)
        if not isinstance(command, list) or not command or any(not isinstance(a, str) for a in command):
            raise ValueError("GCC command must be an argument list")
        output = Path(args.obj)
        output.unlink(missing_ok=True)
        original = Path(args.obj + ".s")
        assembled = Path(args.obj + ".as.s")
        result = subprocess.run(command)
        if result.returncode:
            return result.returncode
        # Ignore injected Python paths/user site packages. maspsx itself is
        # imported from the pinned script's directory and needs only stdlib.
        translated = subprocess.run([sys.executable, "-E", "-s", "-S", args.maspsx,
                                     "--aspsx-version=" + args.version, "--use-comm-section", "-G" + str(args.small_data)],
                                    input=original.read_bytes(), capture_output=True)
        if translated.stderr:
            sys.stderr.buffer.write(translated.stderr)
        if translated.returncode:
            return translated.returncode
        assembled.write_bytes(translated.stdout)
        result = subprocess.run([args.assembler, "-EL", "-mips1", "-mabi=32", "-G0",
                                 "-o", args.obj, str(assembled)])
        if result.returncode:
            output.unlink(missing_ok=True)
        return result.returncode
    except (OSError, ValueError) as error:
        parser.exit(1, f"PS1 compiler pipeline: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
