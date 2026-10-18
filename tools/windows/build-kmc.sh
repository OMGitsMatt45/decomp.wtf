#!/usr/bin/env bash
# Build the original GCC 2.7.2 KMC and binutils 2.6 for Windows, on Linux.
# Debian 13 prerequisites: gcc gcc-mingw-w64-i686-posix binutils-mingw-w64-i686
# mingw-w64-i686-dev make patch git python3. The resulting executables run
# directly on Windows (including x64 through Windows' built-in x86 support).
# Usage: build-kmc.sh SOURCE_DIRECTORY BUILD_DIRECTORY
# SOURCE_DIRECTORY contains pristine gcc/ and binutils/ source trees, as in the
# accompanying source archive, or pristine checkouts of the exact revisions below.
set -euo pipefail
source_dir=$(cd "$1" && pwd)
mkdir -p "$2"
build_dir=$(cd "$2" && pwd)
recipe_dir=$(cd "$(dirname "$0")" && pwd)
windows_cc=${WINDOWS_CC:-i686-w64-mingw32-gcc}
build_cc=${BUILD_CC:-gcc}
windows_ar=${WINDOWS_AR:-i686-w64-mingw32-ar}
windows_ranlib=${WINDOWS_RANLIB:-i686-w64-mingw32-ranlib}
# Upstreams: decompals/mips-gcc-2.7.2@43d1cdb67ed135879869b5266f01efaaada5e35a
# and decompals/mips-binutils-2.6@54514ded39ceb32165a125ddba04ca5b551773a2.
for tree in gcc binutils; do
    test ! -e "$build_dir/$tree"
    cp -a "$source_dir/$tree" "$build_dir/$tree"
    patch -d "$build_dir/$tree" -p1 < "$recipe_dir/patches/$tree-$(if [ "$tree" = gcc ]; then echo 2.7.2; else echo 2.6; fi)-windows.patch"
done
# Python's ZIP extractor does not restore Unix executable mode bits. Restore
# shell scripts by their shebang so the source archive can be unpacked either
# with unzip or Python's cross-platform ZIP support.
python3 - "$build_dir" <<'PYMODES'
from pathlib import Path
import sys
for tree in (Path(sys.argv[1]) / "gcc", Path(sys.argv[1]) / "binutils"):
    for path in tree.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                is_script = stream.read(2) == b"#!"
            if is_script:
                path.chmod(path.stat().st_mode | 0o111)
PYMODES
cp "$recipe_dir/windows_spawn.c" "$build_dir/gcc/"
cd "$build_dir/gcc"
./configure --target=mips-mips-gnu --prefix=/opt/cross --with-gnu-as \
    --host=i386-pc-winnt3.5 --build=i386-pc-linux
"$windows_cc" -c windows_spawn.c -O2 -o windows_spawn.o
touch c-parse.y c-parse.c c-parse.h c-gperf.h cexp.c
make -j"${JOBS:-4}" CC="$windows_cc" HOST_CC="$build_cc" \
    HOST_PREFIX=build- HOST_PREFIX_1=build- \
    HOST_CFLAGS='-std=gnu89 -O0 -w -fno-strict-aliasing -fwrapv' HOST_LDFLAGS= \
    CFLAGS='-std=gnu89 -O0 -w -DHAVE_STRERROR -fno-strict-aliasing -fwrapv' \
    LDFLAGS='-static windows_spawn.o' -o c-parse.y -o c-parse.c -o c-gperf.h -o cexp.c -o bi-parser.c xgcc cc1 cpp cccp
cd "$build_dir/binutils"
CC="$windows_cc" AR="$windows_ar" RANLIB="$windows_ranlib" ./configure \
    --target=mips-kmc-elf --host=i386-pc-winnt3.5 --build=i386-pc-linux \
    --prefix=/opt/cross --disable-gprof --disable-gdb --disable-werror
"$windows_cc" -c "$recipe_dir/windows_tmpfile.c" -O2 -o "$build_dir/windows_tmpfile.o"
for subdir in bfd opcodes libiberty gas; do
    make -j"${JOBS:-4}" -C "$subdir" CC="$windows_cc" \
        CFLAGS='-std=gnu89 -O2 -w -D_WIN32 -D__MSDOS__ -DHAVE_STRERROR' \
        LDFLAGS="-static $build_dir/windows_tmpfile.o"
done
make -j"${JOBS:-4}" -C binutils CC="$windows_cc" \
    CFLAGS='-std=gnu89 -O2 -w -D_WIN32 -D__MSDOS__ -DHAVE_STRERROR' \
    LDFLAGS=-static -o arparse.c -o arlex.c ar objcopy strip.new c++filt
mkdir -p "$build_dir/package"
cp "$build_dir/gcc/xgcc.exe" "$build_dir/package/gcc.exe"
cp "$build_dir/gcc/"{cc1,cpp,cccp}.exe "$build_dir/package/"
cp "$build_dir/binutils/gas/as.new" "$build_dir/package/as.exe"
cp "$build_dir/binutils/binutils/"{ar,objcopy,c++filt}.exe "$build_dir/package/"
cp "$build_dir/binutils/binutils/strip.new" "$build_dir/package/strip.exe"
cp "$build_dir/gcc/COPYING" "$build_dir/package/"
cp "$build_dir/gcc/COPYING.LIB" "$build_dir/package/"
printf 'Native programs and license texts are in %s/package\n' "$build_dir"
