"""Prepare the real toolchains and original homebrew fixtures used by the full CI suite."""

import subprocess
import sys
from pathlib import Path

from decompnet import toolchains

TOOLS = ("gcc-2.7.2-kmc", "gcc-2.7.2-psx", "gcc-2.8.1-psx", "ee-gcc-2.96", "ido-5.3", "ido-7.1",
         "arm-gnu", "binutils-arm", "agbcc", "m2c", "luvdis", "binutils-mips", "gc-wii-binutils", "objdiff-cli", "dtk",
         "sjiswrap", "dtk-template", "mwcc", "mwccarm", "dsd", "cloudflared", "coddog", "maspsx", "ghidra")


def main():
    try:
        for tid in TOOLS:
            toolchains.install(tid, accept_license=True)
            if sys.platform == "win32" and toolchains.get(tid).via_wsl:
                raise RuntimeError(f"{tid} unexpectedly selected WSL")
        if toolchains.get("wibo").supported:
            toolchains.install("wibo")
        root = Path(__file__).resolve().parents[1]
        for script in ("zlib-n64/prepare.py", "demo-rom/build.py", "demo-psx/build.py", "demo-ps2/build.py",
                       "demo-gba/build.py", "demo-ds/build.py", "demo-gc/build.py"):
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
