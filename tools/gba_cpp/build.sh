#!/usr/bin/env bash
# Build on Linux, optionally cross-compile a standalone Windows PE32 executable.
# Usage: build.sh WORK OUTPUT [linux-x86_64|windows-x86_64]
set -euo pipefail
recipe=$(cd "$(dirname "$0")" && pwd)
work=$(realpath -m "${1:?Pass a disposable build directory}")
output=$(realpath -m "${2:?Pass an artifact directory}")
platform=${3:-linux-x86_64}
agbcc=da598c1d918402c42c0c0d7128ba14567f3175e9
gcc=7f236610e99c7a11fb18f056b6446b3c7c40979c
mkdir -p "$work/downloads" "$output"
fetch() {
    local url=$1 file=$2 hash=$3
    if [[ ! -f "$file" ]]; then curl --fail --location --retry 3 "$url" -o "$file"; fi
    printf '%s  %s\n' "$hash" "$file" | sha256sum -c -
}
fetch "https://codeload.github.com/pret/agbcc/tar.gz/$agbcc" "$work/downloads/agbcc.tar.gz" f69ae187a6133b1d353a01a86c1da92a9e38df06c6d3e08e2ae360ea051c1b60
fetch "https://codeload.github.com/gcc-mirror/gcc/tar.gz/$gcc" "$work/downloads/gcc.tar.gz" dd06fa153e90d9acf2769283c446f7529e459ae47496d0522c48b267c88b1c72
# Start fresh so C++ and backend objects can never have different tree layouts,
# host ABIs or OLD_COMPILER settings left over from another build.
rm -rf "$work/source" "$work/package"
mkdir -p "$work/source" "$work/package/bin" "$work/package/source"
tar -xzf "$work/downloads/agbcc.tar.gz" -C "$work/source"
tar -xzf "$work/downloads/gcc.tar.gz" -C "$work/source"
source_dir="$work/source/agbcc-$agbcc"
upstream="$work/source/gcc-$gcc"
# Generate backend tables with the unmodified source, on the build host.
make -C "$source_dir/gcc" -j1 CC="${CC_FOR_BUILD:-gcc}" normal
python3 "$recipe/prepare.py" "$source_dir" "$upstream"
find "$source_dir/gcc" -type f -name '*.o' -delete
generators=(genemit genoutput genrecog genextract genflags gencodes genconfig genpeep gengenrtl gencheck genattr genattrtab genopinit)
keep=()
for generator in "${generators[@]}"; do keep+=(-o "$generator"); done
flags='-O2 -std=gnu11 -fcommon -Werror-implicit-function-declaration -Wno-error=incompatible-pointer-types -static -static-libgcc'
case "$platform" in
    linux-x86_64) compiler=${CC_FOR_BUILD:-gcc}; strip=${STRIP:-strip}; suffix= ;;
    windows-x86_64) compiler=${MINGW_CC:-i686-w64-mingw32-gcc}; strip=${MINGW_STRIP:-i686-w64-mingw32-strip}; suffix=.exe ;;
    *) printf 'Unsupported platform: %s\n' "$platform" >&2; exit 1 ;;
esac
make -C "$source_dir/gcc" -j1 "${keep[@]}" CC="$compiler" BASE_CFLAGS="$flags" \
    rtl.o bitmap.o obstack.o print-rtl.o rtlanal.o cpp
cp "$source_dir/gcc/agbcc-cpp$suffix" "$work/package/bin/agbcc-cpp$suffix"
"$strip" "$work/package/bin/agbcc-cpp$suffix"
cp "$source_dir/gcc/COPYING" "$work/package/COPYING"
# Complete pristine corresponding sources plus every transformation and recipe.
cp "$work/downloads/agbcc.tar.gz" "$work/package/source/agbcc-$agbcc.tar.gz"
cp "$work/downloads/gcc.tar.gz" "$work/package/source/gcc-2.95.3-$gcc.tar.gz"
cp -R "$recipe" "$work/package/source/recipe"
cat > "$work/package/SOURCE.txt" <<EOF
decomp.wtf agbcc-cpp: GCC 2.95.3 C++ frontend + pret/agbcc Thumb backend.
GCC revision: $gcc
agbcc revision: $agbcc
This is an explicitly restored frontend, not an original Nintendo C++ binary.
The existing agbcc C compiler is unchanged. No modern GCC code generator is used.
GPL-2.0-or-later. Complete sources, patches and build instructions are in source/.
Rebuild: bash source/recipe/build.sh WORK OUTPUT $platform
Native $platform; no WSL, Cygwin or MSYS runtime required.
EOF
tar -czf "$output/agbcc-cpp-$platform.tar.gz" -C "$work/package" .
sha256sum "$output/agbcc-cpp-$platform.tar.gz"
