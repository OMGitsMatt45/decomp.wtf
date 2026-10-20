"""Build experimental EE frontends on Linux; this does not install a toolchain."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

from prepare import HERE, checked


HOST_FLAGS = "-std=gnu89 -fcommon -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types"
CFLAGS = "-O0 -w -fno-strict-aliasing -fwrapv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--host", choices=("linux32", "windows"), required=True)
    parser.add_argument("--cc", required=True, help="32-bit host compiler command, including any sysroot options")
    parser.add_argument("--build-cc", default="gcc")
    parser.add_argument("--ar", default="ar")
    parser.add_argument("--ranlib", default="ranlib")
    parser.add_argument("--bison", type=Path, required=True, help="native Bison 1.25 executable")
    parser.add_argument("--bison-data", type=Path, required=True, help="directory containing bison.simple and bison.hairy")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("This source-build recipe requires a Linux build host")
    source, work = args.source.resolve(), args.work.resolve()
    pins = json.loads((HERE / "inputs.json").read_text())
    for name, sha in pins["prepared_files"].items():
        checked(source / name, sha)
    bison = args.bison.resolve()
    version = subprocess.check_output([str(bison), "--version"], text=True).strip()
    if version != "GNU Bison version 1.25":
        parser.error(f"Expected the measured Bison 1.25, got {version!r}")
    if work.exists():
        parser.error("Use a fresh --work directory")
    work.mkdir(parents=True)
    env = os.environ.copy()
    cc = args.cc + " " + HOST_FLAGS
    build_cc = args.build_cc + " " + HOST_FLAGS
    env.update(CC=cc, CC_FOR_BUILD=build_cc, AR=args.ar, RANLIB=args.ranlib,
        CFLAGS=CFLAGS, BISON_SIMPLE=str(args.bison_data.resolve() / "bison.simple"),
        BISON_HAIRY=str(args.bison_data.resolve() / "bison.hairy"))
    host = "i386-pc-linux-gnu" if args.host == "linux32" else "i686-pc-mingw32"
    configure = [str(source / "configure"), "--host=" + host, "--build=i686-pc-linux-gnu",
        "--target=mips64r5900-scei-elf", "--prefix=" + str(work / "not-installed"),
        "--enable-languages=c,c++", "--enable-c-cpplib", "--enable-c-mbchar", "--disable-nls",
        "--disable-shared", "--disable-multilib", "--without-headers", "--with-newlib"]
    suffix = ".exe" if args.host == "windows" else ""
    commands = [configure,
        ["make", "-C", "libiberty", "-j" + str(args.jobs), "CC=" + cc, "AR=" + args.ar,
            "RANLIB=" + args.ranlib, "CFLAGS=" + CFLAGS, "MAKEINFO=true"],
        ["make", "-C", "gcc", "-j" + str(args.jobs),
            *[name + suffix for name in ("cc1", "cc1plus", "xgcc", "cpp0")],
            "CC=" + cc, "HOST_CC=" + build_cc, "AR=" + args.ar, "RANLIB=" + args.ranlib,
            "CFLAGS=" + CFLAGS, "WARN_CFLAGS=", "BISON=" + str(bison), "MAKEINFO=true"]]
    (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    for index, command in enumerate(commands):
        print(shlex.join(command), flush=True)
        with (work / f"step-{index}.log").open("w") as log:
            subprocess.run(command, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Built experimental frontends; parity and exported rebuilds are NOT established.")


if __name__ == "__main__":
    main()
