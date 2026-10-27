"""Prepare the real toolchains and original homebrew fixtures used by the full CI suite."""

import argparse
import subprocess
import sys
from pathlib import Path

from decompnet import toolchains

TOOLS = ("gcc-2.7.2-psx", "gcc-2.8.1-psx", "ee-gcc-2.96",
         "arm-gnu", "binutils-arm", "agbcc", "m2c", "luvdis", "binutils-mips", "objdiff-cli",
         "mwccarm", "dsd", "coddog", "maspsx", "ghidra")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--ds-only", action="store_true", help="prepare the native Nintendo DS qualification")
    scope.add_argument("--psx-only", action="store_true", help="prepare native PS1 C/C++ and disc qualification")
    args = parser.parse_args()
    selected = (("gcc-2.7.2-psx", "gcc-2.8.1-psx", "binutils-mips", "m2c", "maspsx") if args.psx_only else
                ("arm-gnu", "mwccarm", "dsd", "objdiff-cli", "m2c") if args.ds_only else TOOLS)
    fixtures = ("zlib/prepare.py", "demo-psx/build.py") if args.psx_only else ("zlib/prepare.py", "demo-ds/build.py") if args.ds_only else (
        "zlib/prepare.py", "demo-psx/build.py", "demo-ps2/build.py",
        "demo-gba/build.py", "demo-ds/build.py")
    try:
        for tid in selected:
            toolchains.install(tid, accept_license=True)
            if sys.platform == "win32" and toolchains.get(tid).via_wsl:
                raise RuntimeError(f"{tid} unexpectedly selected WSL")
        if not args.psx_only and toolchains.get("wibo").supported:
            toolchains.install("wibo")
        root = Path(__file__).resolve().parents[1]
        for script in fixtures:
            result = subprocess.run([sys.executable, str(root / "projects" / script)], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=600)
            if result.returncode:
                raise RuntimeError(f"{script} failed:\n{(result.stdout + result.stderr)[-5000:]}")
            print(f"prepared {script}", flush=True)
    except Exception as error:
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::{message}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
