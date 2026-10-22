#!/usr/bin/env python3
"""Run ds-decomp extraction and reject a secure area it could not decrypt.

dsd can warn about an invalid decrypted prefix and still exit successfully.
Such output must not become the reference objects used to judge source.
"""

import subprocess
import sys


def main(argv: list[str]) -> int:
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode:
        return result.returncode
    if "Failed to decrypt secure area" in result.stdout + result.stderr:
        print("error: the ARM7 BIOS did not validate the ROM's encrypted secure area. "
              "Check your BIOS and game copy; nonstandard secure-area prefixes are not supported.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
