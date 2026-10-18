#!/usr/bin/env python3
"""Build the N64 C++ library shipped with the app. End users do not need a compiler."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["windows", "linux", "macos"],
                        default={"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux"))
    parser.add_argument("--cxx", default=os.environ.get("N64_CXX", ""))
    parser.add_argument("--sysroot", help="optional sysroot for a portable Linux release build")
    args = parser.parse_args()
    compiler = args.cxx or shutil.which("g++") or shutil.which("clang++")
    if not compiler and sys.platform == "win32":
        for candidate in ("C:/msys64/mingw64/bin/g++.exe", "C:/mingw64/bin/g++.exe"):
            if Path(candidate).is_file():
                compiler = candidate
                break
    if not compiler:
        parser.error("install a C++17 compiler or pass --cxx=/path/to/g++")
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    suffix = {"windows": "dll", "linux": "so", "macos": "dylib"}[args.target]
    output = ROOT / "src/decompnet/_native" / f"n64-{args.target}-{machine}.{suffix}"
    output.parent.mkdir(exist_ok=True)
    flags = ["-std=c++17", "-O2", "-shared", "-s", "-ffile-prefix-map=" + str(ROOT) + "=."]
    if args.sysroot:
        flags += ["--sysroot=" + args.sysroot]
    if args.target == "windows":
        flags += ["-static", "-Wl,--no-insert-timestamp"]
    elif args.target == "linux":
        flags += ["-fPIC", "-fvisibility=hidden", "-static-libstdc++", "-static-libgcc"]
    else:
        flags += ["-fPIC", "-fvisibility=hidden"]
    subprocess.run([compiler, *flags, str(ROOT / "native/n64/n64.cpp"), "-o", str(output)], check=True)
    print("Built", output.relative_to(ROOT))


if __name__ == "__main__":
    main()
