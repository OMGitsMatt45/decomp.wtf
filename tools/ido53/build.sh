#!/usr/bin/env bash
# Build the authentic IRIX 5.3 SGI/EDG frontend and its NCC driver.
# This archive overlays the pinned 5.3 C suite; it never replaces its backend.
# Usage: build.sh BUILD_DIRECTORY OUTPUT_DIRECTORY
set -euo pipefail
build_dir=$(mkdir -p "$1" && cd "$1" && pwd)
out_dir=$(mkdir -p "$2" && cd "$2" && pwd)
recipe_dir=$(cd "$(dirname "$0")" && pwd)
revision=d5aec59932034b8a20f23f471297a55c45dcbc45
git -c core.autocrlf=false clone https://github.com/decompals/ido-static-recomp.git "$build_dir/source"
cd "$build_dir/source"
git config core.autocrlf false
git checkout --detach "$revision"
git apply "$recipe_dir/native-edg.patch"
make -j2 RELEASE=1 setup
make -j2 RELEASE=1 VERSION=5.3 IDO_TC='cc edgcpfe' LDFLAGS='-static-libgcc -lm'
platform=linux-x86_64
suffix=
if [[ ${OS:-} == Windows_NT ]]; then platform=windows-x86_64; suffix=.exe; fi
package="$build_dir/package"
mkdir -p "$package"
cp "build/5.3/out/cc$suffix" "$package/NCC$suffix"
cp "build/5.3/out/edgcpfe$suffix" "$package/"
cp "$recipe_dir/build.sh" "$recipe_dir/native-edg.patch" .
sha256sum ido/5.3/usr/bin/cc ido/5.3/usr/lib/DCC/edgcpfe > "$package/IRIX-SHA256SUMS"
printf '%s\n' "Upstream: decompals/ido-static-recomp@$revision" \
    'IDO 5.3 SGI/EDG 2.19 C++ frontend; NCC is the original 5.3 cc driver in C++ mode.' \
    'Overlay for the original 5.3 suite. uopt, ugen and as1 are not replaced.' \
    'Proprietary SGI programs. See the upstream IDO license and corresponding source archive.' \
    > "$package/IDO53-CPP.txt"
tar --exclude=.git --exclude=build --exclude=tools/rabbitizer/build \
    -czf "$out_dir/ido53-cpp-$platform-source-v1.tar.gz" .
tar -czf "$out_dir/ido53-cpp-$platform-v1.tar.gz" -C "$package" .
cd "$out_dir"
sha256sum ido53-cpp-*.tar.gz > SHA256SUMS
