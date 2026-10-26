"""Build Demo Quest PS2, a PlayStation 2 executable made only from code we may share: the same Demo Quest game,
main loop and tiny libc as the shared console fixture (CC0, ../shared-game/runtime, ../shared-game/original) and zlib 1.1.4 (Zlib
license), compiled with EE-GCC 2.96 at -O2 -G8 and linked at 0x00100000 like PS2 games.

    uv run python projects/demo-ps2/build.py    ->  build/SLUS_999.99 (stripped, like a game) + build/demoq_ps2.elf
"""

from __future__ import annotations

import shutil
import argparse
import subprocess
import sys
from pathlib import Path

from decompnet import toolchains
from decompnet.compiler import run_in
from decompnet.project import compiler_config

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
DEMO = HERE.parent / "shared-game" / "runtime"
GAME = HERE.parent / "shared-game" / "original"
ZLIB = HERE.parent / "zlib"
ZLIB_UNITS = ["adler32", "compress", "crc32", "deflate", "inflate", "infblock", "infcodes", "inffast", "inftrees",
              "infutil", "trees", "uncompr", "zutil"]


def run(argv, cwd=None):
    res = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    if res.returncode != 0:
        sys.exit(f"failed: {' '.join(map(str, argv))}\n{res.stdout}{res.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BUILD)
    args = parser.parse_args()
    build = args.output.resolve()
    if build.exists():
        shutil.rmtree(build)
    (build / "src").mkdir(parents=True)
    # This is our own C-built target fixture; compile trusted source natively.
    # Copy inputs to keep paths portable for the period driver.
    for name, src in (("demo", DEMO), ("game", GAME), ("zlib", ZLIB / "original"), ("sysinclude", ZLIB / "sysinclude")):
        shutil.copytree(src, build / "src" / name)
    shutil.copy(HERE / "crt0.s", build / "src" / "crt0.s")
    shutil.copy(HERE / "ps2rt.c", build / "src" / "ps2rt.c")
    cfg = compiler_config(build, {"compiler": {"toolchain": "ee-gcc-2.96", "language": "c", "sandbox": "none"}})
    cc = cfg.cmd[:cfg.cmd.index("-I{include}")]  # driver + -c
    cc = [a for a in cc if a not in ("-O2", "-G0")]
    jobs = [("src/crt0.s", []), ("src/demo/main.c", ["-Isrc/game"]), ("src/demo/libc.c", []), ("src/ps2rt.c", []),
            ("src/game/game.c", ["-Isrc/game"])]
    jobs += [(f"src/zlib/{u}.c", ["-Isrc/sysinclude", "-Isrc/zlib"]) for u in ZLIB_UNITS]
    objs = []
    for src, extra in jobs:
        obj = f"{Path(src).stem}.o"
        res = run_in(cfg, build, [*cc, "-O2", "-G8", *extra, src, "-o", obj], inputs=["src"], outputs=[obj])
        if res.returncode != 0:
            sys.exit(f"failed: {src}\n{res.stdout}{res.stderr}")
        objs.append(obj)
    elf = build / "demoq_ps2.elf"
    # the EE assembler writes .rel and .rela sections for the same section, which only GNU ld links
    ld = str(toolchains.binary("binutils-mips").parent / "mips-ps2-decompals-ld")
    run([ld, "-EL", "-T", str(HERE / "elf.ld"), "-o", str(elf), *objs], cwd=build)
    game = build / "SLUS_999.99"
    run([str(Path(ld).with_name("mips-ps2-decompals-objcopy")), "--strip-all", str(elf), str(game)])
    print(f"built {game} ({game.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
