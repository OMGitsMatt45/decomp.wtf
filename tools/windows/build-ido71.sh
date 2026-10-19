#!/usr/bin/env bash
# Rebuild IDO's native Windows programs under MSYS2; bundle their POSIX runtime.
# The SGI frontend/backend programs are preserved by static recompilation.
# Usage: build-ido71.sh BUILD_DIRECTORY OUTPUT_DIRECTORY
set -euo pipefail
build_dir=$(mkdir -p "$1" && cd "$1" && pwd)
out_dir=$(mkdir -p "$2" && cd "$2" && pwd)
recipe_dir=$(cd "$(dirname "$0")" && pwd)
revision=9c242adc890beef098020149d9554f48208f699d
git clone https://github.com/decompals/ido-static-recomp.git "$build_dir/source"
cd "$build_dir/source"
git checkout --detach "$revision"
# MSYS uses 64 KiB allocation pages. IDO 7.1's guest libc starts at
# 0x0fb4c000, which needs the containing page, not an aligned guest address.
# The MSYS memory_allocate path uses mprotect, preserving existing page data.
python - <<'PY'
from pathlib import Path
p = Path('libc_impl.c')
s = p.read_text()
old = 'memory_allocate(mem, LIBC_ADDR, (LIBC_ADDR + LIBC_SIZE));'
assert s.count(old) == 1
p.write_text(s.replace(old, 'memory_allocate(mem, TRUNC_PAGE(LIBC_ADDR), ROUND_PAGE(LIBC_ADDR + LIBC_SIZE));'))
# Modern MSYS/newlib's __assert argument order differs from the historical
# host prototype. Preserve the diagnostic and abort without a host ABI guess.
s = p.read_text()
old = '__assert(assertion, file, line);'
assert s.count(old) == 1
p.write_text(s.replace(old, 'fprintf(stderr, "Assertion failed: %s, file %s, line %d\\n", assertion, file, line); abort();'))
PY
make -j2 RELEASE=1 setup
make -j2 RELEASE=1 VERSION=7.1 LDFLAGS='-static-libgcc -lm'
package="$build_dir/package"
mkdir -p "$package/licenses"
cp build/7.1/out/* "$package/"
# The release used to rely on a system-wide MSYS installation. Every runtime
# dependency now travels beside the executables, including child processes.
while IFS= read -r dll; do cp "$dll" "$package/"; done < <(
    ldd build/7.1/out/*.exe | awk '/=> \/usr\/bin\// {print $3}' | sort -u
)
test -f "$package/msys-2.0.dll"
if test -d /usr/share/licenses/msys2-runtime; then
    cp -r /usr/share/licenses/msys2-runtime "$package/licenses/"
fi
runtime_version=$(pacman -Q msys2-runtime | awk '{print $2}')
runtime_source="msys2-runtime-$runtime_version.src.tar.zst"
curl -fL "https://repo.msys2.org/msys/sources/$runtime_source" -o "$out_dir/$runtime_source"
cp "$recipe_dir/build-ido71.sh" ./build-ido71.sh
printf '%s\n' "Upstream: decompals/ido-static-recomp@$revision" \
    "MSYS2 runtime: $runtime_version (bundled DLL and corresponding source)" \
    'IDO is proprietary. The original compiler algorithms are unchanged.' \
    'Host fix: map the page containing the IDO 7.1 guest libc.' > "$package/BUILD.txt"
pacman -Q > "$package/BUILD-PACKAGES.txt"
tar --exclude=.git --exclude=build --exclude=tools/rabbitizer/build \
    -czf "$out_dir/ido-7.1-windows-source-v1.tar.gz" .
tar -czf "$out_dir/ido-7.1-windows-v1.tar.gz" -C "$package" .
runtime_dir="$build_dir/runtime"
mkdir -p "$runtime_dir"
cp "$package/"*.dll "$runtime_dir/"
cp -r "$package/licenses" "$runtime_dir/"
cp "$package/BUILD-PACKAGES.txt" "$runtime_dir/"
tar -czf "$out_dir/ido-windows-runtime-v1.tar.gz" -C "$runtime_dir" .
cd "$out_dir"
sha256sum ido-7.1-windows-v1.tar.gz ido-windows-runtime-v1.tar.gz ido-7.1-windows-source-v1.tar.gz "$runtime_source" > SHA256SUMS
