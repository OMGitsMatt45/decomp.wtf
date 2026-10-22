#!/usr/bin/env python3
"""Run ds-decomp extraction and reject a secure area it could not decrypt.

dsd can warn about an invalid decrypted prefix and still exit successfully.
Such output must not become the reference objects used to judge source.
"""

import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str]) -> int:
    output = argv.index("--output-path") + 1
    target = Path(argv[output]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # dsd writes config.yaml before validating the secure area. Keep partial
    # output away from Ninja's dependency target and existing reference data.
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-extract-", dir=target.parent) as temporary:
        staged = Path(temporary) / "rom"
        command = [*argv[:output], str(staged), *argv[output + 1:]]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=3500)
        except subprocess.TimeoutExpired:
            print("error: ds-decomp ROM extraction timed out", file=sys.stderr)
            return 124
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode:
            return result.returncode
        if "Failed to decrypt secure area" in result.stdout + result.stderr:
            print("error: the ARM7 BIOS did not validate the ROM's encrypted secure area. "
                  "Check your BIOS and game copy; nonstandard secure-area prefixes are not supported.", file=sys.stderr)
            return 1
        previous = Path(temporary) / "previous"
        if target.exists():
            target.replace(previous)
        try:
            staged.replace(target)
        except OSError:
            if previous.exists():
                previous.replace(target)
            raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
