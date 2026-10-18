#!/usr/bin/env python3
"""Build the Windows KMC suite from C++ implementation files, on Linux.

Usage: python3 build_kmc_cpp.py PRISTINE_SOURCE_DIRECTORY NEW_BUILD_DIRECTORY
Requires Python 3.10+, make, patch, native GCC and i686 MinGW GCC/G++/binutils.
The original C build configures the historical target and supplies typed K&R
definitions. Its runtime objects are ALL replaced before the final link.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

RECIPE = Path(__file__).resolve().parent
PROGRAMS = {
    "gcc/xgcc.exe": "gcc.exe", "gcc/cc1.exe": "cc1.exe",
    "gcc/cc1plus.exe": "cc1plus.exe",
    "gcc/cccp.exe": "cccp.exe", "gcc/cpp.exe": "cpp.exe",
    "binutils/gas/as.new": "as.exe", "binutils/binutils/ar.exe": "ar.exe",
    "binutils/binutils/objcopy.exe": "objcopy.exe",
    "binutils/binutils/strip.new": "strip.exe", "binutils/binutils/c++filt.exe": "c++filt.exe",
}
LINK_OUTPUTS = {"xgcc", "cccp", "cc1", "../cc1plus", "as.new", "objcopy", "ar", "strip.new", "c++filt"}


def command(arguments, cwd=None, env=None):
    subprocess.run(list(map(str, arguments)), cwd=cwd, env=env, check=True)


def finish(build, cxx, ar, strip):
    base = build / "baseline"
    records = json.loads((build / "conversion-records.json").read_text())
    objects = set()
    inventory = []
    for row in records:
        args, cwd, source = row["args"], Path(row["cwd"]), Path(row["source"])
        compiled_name = next(item for item in reversed(args) if item.endswith(".c"))
        output = cwd / args[args.index("-o") + 1] if "-o" in args else cwd / (Path(compiled_name).stem + ".o")
        converted = Path(row["work"])
        shutil.copyfile(converted / "implementation.o", output)
        objects.add(output.resolve())
        inventory.append({"source": str(source.relative_to(base)) if source.is_relative_to(base) else source.name,
                          "cpp": str((converted / "implementation.cpp").relative_to(build)),
                          "language": "GNU C++98", "object": str(output.relative_to(base)),
                          "source_sha256": hashlib.sha256((converted / "implementation.cpp").read_bytes()).hexdigest(),
                          "object_sha256": hashlib.sha256(output.read_bytes()).hexdigest()})
    for archive_name, members in json.loads((build / "archive-members.json").read_text()).items():
        archive = base / archive_name
        for member in members:
            if (archive.parent / member).resolve() not in objects:
                raise RuntimeError(f"Archive member was not built as C++: {archive_name}/{member}")
        archive.unlink()
        command([ar, "rcs", archive, *members], cwd=archive.parent)
    linked = set()
    for row in map(json.loads, (build / "compiler-commands.jsonl").read_text().splitlines()):
        args = row["args"]
        if "-c" in args or "-o" not in args or args[args.index("-o") + 1] not in LINK_OUTPUTS:
            continue
        for item in args:
            if item.endswith(".o") and (Path(row["cwd"]) / item).resolve() not in objects:
                raise RuntimeError(f"Link object was not built as C++: {item}")
        command([cxx, *args], cwd=row["cwd"])
        linked.add(args[args.index("-o") + 1])
    if linked != LINK_OUTPUTS:
        raise RuntimeError(f"Incomplete C++ link inventory: {linked}")
    if not os.path.samefile(base / "gcc/cccp.exe", base / "gcc/cpp.exe"):
        shutil.copyfile(base / "gcc/cccp.exe", base / "gcc/cpp.exe")
    package = build / "package"
    package.mkdir(exist_ok=True)
    for source, name in PROGRAMS.items():
        shutil.copyfile(base / source, package / name)
        command([strip, "--strip-all", package / name])
    for name in ("COPYING", "COPYING.LIB"):
        shutil.copyfile(base / "gcc" / name, package / name)
    (package / "CPP-BUILD.json").write_text(json.dumps({
        "compiler": subprocess.check_output([cxx, "--version"], text=True).splitlines()[0],
        "translation_units": inventory,
        "note": "Every project runtime object is built from C++. Generic MinGW system/runtime libraries are linked statically.",
    }, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("build", type=Path)
    options = parser.parse_args()
    build = options.build.resolve()
    build.mkdir(parents=True, exist_ok=False)
    cc = shutil.which(os.environ.get("WINDOWS_CC", "i686-w64-mingw32-gcc"))
    cxx = shutil.which(os.environ.get("WINDOWS_CXX", "i686-w64-mingw32-g++"))
    ar = shutil.which(os.environ.get("WINDOWS_AR", "i686-w64-mingw32-ar"))
    strip = shutil.which(os.environ.get("WINDOWS_STRIP", "i686-w64-mingw32-strip"))
    if not all((cc, cxx, ar, strip)):
        parser.error("the i686 MinGW C/C++ compiler and binutils must be on PATH")
    recorder = RECIPE / "record_cc.py"
    recorder.chmod(recorder.stat().st_mode | 0o111)
    env = dict(os.environ, N64_REAL_CC=cc, N64_CC_LOG=str(build / "compiler-commands.jsonl"), WINDOWS_CC=str(recorder))
    command(["bash", RECIPE / "build-kmc.sh", options.source.resolve(), build / "baseline"], env=env)
    archives = {}
    for archive in sorted((build / "baseline").rglob("*.a")):
        archives[str(archive.relative_to(build / "baseline"))] = subprocess.check_output([ar, "t", archive], text=True).splitlines()
    (build / "archive-members.json").write_text(json.dumps(archives, indent=2))
    command(["python3", RECIPE / "port_kmc_cpp.py", build, "--cc", cc, "--cxx", cxx,
             "--jobs", os.environ.get("JOBS", "4")])
    finish(build, cxx, ar, strip)
    print("C++ programs, build inventory and licenses:", build / "package")


if __name__ == "__main__":
    main()
