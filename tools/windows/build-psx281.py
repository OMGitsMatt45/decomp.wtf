#!/usr/bin/env python3
"""Cross-build old-gcc 0.17's PSX GCC 2.8.1 C compiler for native Windows.

Use the original GNU gcc-2.8.1.tar.gz and the patches from decompals/old-gcc
cf70ec58bce58128732062bc9930045c82904cbb. Target code generation is unchanged.
Requires GNU make, patch, a native GCC, and i686-w64-mingw32-gcc on Linux.
"""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def edit(path, before, after, count=1):
    text = path.read_text()
    if text.count(before) != count:
        raise RuntimeError(f"{path}: expected {count} occurrences of {before!r}")
    path.write_text(text.replace(before, after))


def build(args):
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != "3b30fbfdf93e628373d90d174243f3267b0eec9ebe792bb64fd15b8828c2ea4c":
        raise RuntimeError("Expected the original GNU gcc-2.8.1.tar.gz")
    args.work.mkdir(parents=True, exist_ok=False)
    with tarfile.open(args.source) as archive:
        archive.extractall(args.work, filter="data")
    work = args.work / "gcc-2.8.1"
    for path in work.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode | 0o200)
    env = dict(os.environ, PATH=str(args.mingw_bin) + os.pathsep + os.environ["PATH"],
               CC="i686-w64-mingw32-gcc", CFLAGS="-std=gnu89 -w")

    def run(command, **kwargs):
        subprocess.run([str(a) for a in command], cwd=work, env=env, check=True, **kwargs)

    for path in work.glob("*.c"):
        path.write_text(path.read_text().replace("include <varargs.h>", "include <stdarg.h>"))
    for name, patch in [("obstack.h", "obstack-2.8.1.h.patch"), ("config/mips/mips.h", "mips.patch")]:
        run(["patch", "-u", "-p1", name, "-i", args.patches / patch])
    with (args.patches / "psx.patch").open() as patch:
        run(["patch", "-su", "-p1"], stdin=patch)
    # The old CRT spawn API loses spaces in arguments. Use the same quoting
    # helper as the 2.7.2 port and preserve all child failures in wait status.
    edit(work / "pexecute.c", "extern int _spawnv ();\nextern int _spawnvp ();",
         "extern int windows_spawnv ();\nextern int windows_spawnvp ();")
    edit(work / "pexecute.c", "_spawnvp : _spawnv", "windows_spawnvp : windows_spawnv")
    edit(work / "pexecute.c", "(_P_NOWAIT, program, fix_argv (argv));", "(_P_NOWAIT, program, argv);")
    edit(work / "pexecute.c", "pid = cwait (&termstat, pid, WAIT_CHILD);", "pid = _cwait (&termstat, pid, _WAIT_CHILD);")
    edit(work / "pexecute.c", "*status = (((termstat) & 0xff) << 8);", "*status = termstat ? (1 << 8) : 0;")
    # Native Windows cannot unlink an open FILE, and its temp directory is
    # normally in the user's profile rather than /tmp or the drive root.
    mips = work / "config/mips/mips.c"
    edit(mips, '  int len;\n\n  if (base == (char *)0)\n', '''  int len;

#ifdef _WIN32
  if (base == (char *)0 || *base == 0)
    base = getenv ("TEMP");
  if (base == (char *)0 || *base == 0)
    base = getenv ("TMP");
  if (base == (char *)0 || *base == 0)
    base = ".";
#endif

  if (base == (char *)0)
''')
    edit(mips, "#ifndef __MSDOS__\n  /* In MSDOS, we cannot unlink", "#if !defined(__MSDOS__) && !defined(_WIN32)\n  /* In MSDOS and Windows, we cannot unlink")
    edit(mips, "#ifdef __MSDOS__\n      unlink (temp_filename);", "#if defined(__MSDOS__) || defined(_WIN32)\n      unlink (temp_filename);")
    shutil.copyfile(Path(__file__).with_name("windows_spawn.c"), work / "windows_spawn.c")
    for generated in ("c-parse.c", "c-parse.h", "c-gperf.h", "cexp.c"):
        os.utime(work / generated, None)
    # This autoconf predates automatic detection of MinGW's .exe suffix.
    configure = work / "configure"
    text = configure.read_text().replace("-o conftest $CFLAGS", "-o conftest.exe $CFLAGS")
    text = text.replace("test -s conftest", "test -s conftest.exe").replace("./conftest;", "./conftest.exe;")
    configure.write_text(text)
    with (work / "configure-windows.log").open("w") as log:
        run(["./configure", "--host=i386-pc-mingw32", "--build=i386-pc-linux", "--target=mips-sony-psx", "--with-endian-little", "--with-gnu-as", "--prefix=/decompnet"], stdout=log, stderr=subprocess.STDOUT)
    run(["i686-w64-mingw32-gcc", "-c", "windows_spawn.c", "-o", "windows_spawn.o"])
    with (work / "build-windows.log").open("w") as log:
        run(["make", f"-j{args.jobs}", "exeext=.exe", "CC=i686-w64-mingw32-gcc", "HOST_CC=gcc", "HOST_PREFIX=build-", "HOST_PREFIX_1=build-", "HOST_CFLAGS=-std=gnu89 -O2 -w", "HOST_LDFLAGS=", "CFLAGS=-std=gnu89 -O2 -w -DHAVE_STRERROR", "LDFLAGS=-static windows_spawn.o", "cpp", "cc1", "xgcc"], stdout=log, stderr=subprocess.STDOUT)
    args.output.mkdir(parents=True, exist_ok=True)
    for source, target in [("xgcc.exe", "gcc.exe"), ("cpp.exe", "cpp.exe"), ("cc1.exe", "cc1.exe"), ("COPYING", "COPYING"), ("COPYING.LIB", "COPYING.LIB")]:
        shutil.copyfile(work / source, args.output / target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "patches", "work", "output", "mingw-bin"):
        parser.add_argument("--" + name, required=True, type=lambda p: Path(p).resolve())
    parser.add_argument("--jobs", type=int, default=4)
    build(parser.parse_args())
