"""Restore GCC 2.95.3's C++ language frontend to a disposable agbcc source tree.

Only the separate agbcc-cpp executable uses this tree. The distributed agbcc C
compiler is never rebuilt or replaced by this recipe.
"""

import shutil
import subprocess
import sys
from pathlib import Path


def prepare(agbcc: Path, upstream: Path) -> None:
    here = Path(__file__).resolve().parent
    gcc = agbcc / "gcc"
    shutil.copytree(upstream / "gcc/cp", gcc / "cp")
    for path in (gcc / "cp").rglob("*"):
        if path.suffix in (".c", ".h"):
            path.write_text(path.read_text().replace("unsigned HOST_WIDE_INT", "HOST_WIDE_UINT"))
    for name in ("c-pragma.c", "c-pragma.h"):
        shutil.copyfile(upstream / "gcc" / name, gcc / name)
    shutil.copyfile(upstream / "gcc/gansidecl.h", gcc / "cpp-gansidecl.h")
    (gcc / "cpp-common.c").write_text((upstream / "gcc/c-common.c").read_text().replace(
        "unsigned HOST_WIDE_INT", "HOST_WIDE_UINT"))
    for name in ("cpp-glue.c", "cpp-port.h"):
        shutil.copyfile(here / name, gcc / name)
    with (gcc / "cp/cp-tree.h").open("a") as out:
        out.write((here / "cp-declarations.h").read_text())
    subprocess.run(["patch", "-p1", "-i", str(here / "backend.patch")], cwd=agbcc, check=True)
    makefile = (here / "cpp.mk").read_text().replace("@UPSTREAM@", upstream.as_posix())
    with (gcc / "Makefile").open("a") as out:
        out.write(makefile)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
