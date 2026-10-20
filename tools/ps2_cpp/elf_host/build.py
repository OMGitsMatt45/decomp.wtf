"""Build experimental Win32 hosts for the checksum-pinned original EE compiler.

Requires an i686 MinGW C compiler. Output is a separate research directory;
this never installs, registers, or substitutes an application toolchain.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import traceback
import urllib.request

from prepare import generate

HERE = Path(__file__).resolve().parent
ARCHIVE_SHA256 = "0590d2ca9da8f5903889d66761220d14b47a8d14ba987ca53db84a1650a1fd0a"
REVISION = "597c1b349fcbda26ba75a4e3a4fb136c26887d7a"
HELPERS = {
    "COPYING": "dcc100d4161cc0b7177545ab6e47216f84857cda3843847c792a25289852dcaa",
    "COPYING.LIB": "d7bf9d064ac3e5840f9dd02422b7eeec4f1fd03f37fadbd043602be5e882304f",
    "libiberty/obstack.c": "23095bce268a8c30871cd1c836c2ce87db2a1e90f789cd15158ac52f4b877b19",
    "include/obstack.h": "ed45d84bb4f3c8a62b4228042ca31fe0f6ffd3150ccb6a8f1000fabd2a0be351",
    "libiberty/getopt.c": "cff01bf0e5c6abeb6bfdaf899d49cbdcd2efdb75f813c1b981dcdcbaeecf5073",
    "libiberty/getopt1.c": "48f141d2f0423ad971e82eafc2f71ca1e62a6f4df0ccb983cc7bd751ec203454",
    "include/getopt.h": "fbf24752ced82730dd6a0a214b8b6d115cec61a8bbab8209f37fccb731bf720f",
}
TOOLS = ("bin/ee-gcc", "bin/ee-as", "lib/gcc-lib/ee/2.96-ee-001003-1/cc1",
         "lib/gcc-lib/ee/2.96-ee-001003-1/cc1plus", "lib/gcc-lib/ee/2.96-ee-001003-1/cpp0")


def checked(path: Path, expected: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Unexpected SHA-256: {path}")


def build(archive: Path, output: Path, cc: str, objcopy: str) -> None:
    checked(archive, ARCHIVE_SHA256)
    if output.exists():
        raise ValueError("Use a fresh output directory")
    output.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(output, filter="data")
    work = output / "host-source"
    work.mkdir()
    shutil.copyfile(HERE / "host.c", work / "host.c")
    for path, sha in HELPERS.items():
        target = work / Path(path).name
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/gcc-mirror/gcc/{REVISION}/{path}", timeout=60) as response:
            target.write_bytes(response.read())
        checked(target, sha)
    report = dict(experimental=True, archive_sha256=ARCHIVE_SHA256,
                  host_compiler=subprocess.check_output([cc, "--version"], text=True).splitlines()[0], tools={})
    for tool in TOOLS:
        report["tools"][tool] = generate(output / tool, work / "image.h")
        shutil.copyfile(output / tool, work / "payload.elf")
        subprocess.run([objcopy, "-I", "binary", "-O", "pe-i386", "-B", "i386",
                        "--rename-section", ".data=.eepay,alloc,load,readonly,data,contents",
                        "payload.elf", "payload.o"], cwd=work, check=True)
        # The pinned GNU helpers contain K&R definitions, removed in C23.
        # Modern MinGW may default to gnu23; select a compatible host dialect.
        command = [cc, "-std=gnu11", "-O2", "-g", "-DHAVE_STDLIB_H", "-DHAVE_STRING_H", "-include", "stdlib.h",
                   "-include", "string.h", "-I" + str(work), str(work / "host.c"),
                   *[str(work / name) for name in ("obstack.c", "getopt.c", "getopt1.c")],
                   str(work / "payload.o"), "-o", str(output / (tool + ".exe"))]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.stdout:
            print(result.stdout, flush=True)
        if result.returncode:
            raise RuntimeError(f"Host compiler failed for {tool} (exit {result.returncode}):\n{result.stdout[-14000:]}")
        shutil.copyfile(work / "image.h", work / (Path(tool).name + "-image.h"))
        print("Built " + tool + ".exe", flush=True)
    # The exact original driver searches these aliases relative to its prefix.
    for alias, tool in {"ee/bin/as": "bin/ee-as", "bin/ee-g++": "bin/ee-gcc", "bin/ee-cpp": "bin/ee-gcc"}.items():
        shutil.copyfile(output / (tool + ".exe"), output / (alias + ".exe"))
    (output / "host-build.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--objcopy", required=True)
    args = parser.parse_args()
    try:
        build(args.archive.resolve(), args.output.resolve(), args.cc, args.objcopy)
    except Exception:
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write("## EE host build failed\n\n```text\n" + traceback.format_exc()[-16000:] + "\n```\n")
        raise
