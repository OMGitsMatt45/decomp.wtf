#!/usr/bin/env bash
# Cross-build pret/agbcc as native 32-bit Windows programs on Linux.
# Requirements: gcc, make, Python 3, and an i686-w64-mingw32 GCC toolchain.
# Source: https://github.com/pret/agbcc
# Pinned revision: da598c1d918402c42c0c0d7128ba14567f3175e9
# Usage: bash build-agbcc.sh /path/to/agbcc /path/to/output
# The source directory is a disposable checkout: generated files are replaced.
set -euo pipefail

source_dir=$(realpath "${1:?Pass the agbcc source directory}")
output_dir=$(realpath -m "${2:?Pass an output directory}")
build_cc=${CC_FOR_BUILD:-gcc}
windows_cc=${MINGW_CC:-i686-w64-mingw32-gcc}
windows_strip=${MINGW_STRIP:-i686-w64-mingw32-strip}
revision=da598c1d918402c42c0c0d7128ba14567f3175e9

mkdir -p "$output_dir/bin" "$output_dir/include" "$output_dir/source"

# Upstream's generators run on the build host. Keep those Linux executables
# while recompiling every compiler object with MinGW; the released programs
# consequently have no Linux, Cygwin, MSYS, or WSL runtime dependency.
make -C "$source_dir/gcc" clean
make -C "$source_dir/gcc" -j1 CC="$build_cc"
generators=(genemit genoutput genrecog genextract genflags gencodes genconfig
            genpeep gengenrtl gencheck genattr genattrtab genopinit)
keep_generators=()
for generator in "${generators[@]}"; do
    keep_generators+=(-o "$generator")
done
flags='-O2 -std=gnu11 -Werror-implicit-function-declaration -Wno-error=incompatible-pointer-types -static -static-libgcc'
for variant in normal old; do
    find "$source_dir/gcc" -maxdepth 1 -type f -name '*.o' -delete
    # The support objects must be explicit targets because their usual
    # generator prerequisites are deliberately retained from the host build.
    variant_flags=$flags
    if [[ $variant == old ]]; then variant_flags+=' -DOLD_COMPILER'; fi
    make -C "$source_dir/gcc" -j1 "${keep_generators[@]}" \
        CC="$windows_cc" BASE_CFLAGS="$variant_flags" \
        rtl.o bitmap.o obstack.o print-rtl.o rtlanal.o "$variant"
    binary=agbcc
    if [[ $variant == old ]]; then binary=old_agbcc; fi
    cp "$source_dir/gcc/$binary.exe" "$output_dir/bin/$binary.exe"
    "$windows_strip" "$output_dir/bin/$binary.exe"
done

cp -R "$source_dir/libc/include/." "$output_dir/include/"
cp -R "$source_dir/ginclude/." "$output_dir/include/"
cp "$source_dir/gcc/COPYING" "$output_dir/COPYING"
cp "$source_dir/libiberty/COPYING.LIB" "$output_dir/COPYING.LIB"
cp "${BASH_SOURCE[0]}" "$output_dir/source/build-agbcc.sh"

# Include the complete corresponding upstream source, alongside this recipe.
# An extracted source distribution can also be rebuilt without Git installed.
if git -C "$source_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    actual_revision=$(git -C "$source_dir" rev-parse HEAD)
    if [[ $actual_revision != "$revision" ]]; then
        printf 'Expected agbcc revision %s; got %s\n' "$revision" "$actual_revision" >&2
        exit 1
    fi
    git -C "$source_dir" archive --format=tar.gz --prefix="agbcc-$revision/" \
        "$revision" > "$output_dir/source/agbcc-$revision.tar.gz"
else
    tar -C "$(dirname "$source_dir")" --exclude='*.o' --exclude='*.exe' \
        --exclude='.git' -czf "$output_dir/source/agbcc-$revision.tar.gz" \
        "$(basename "$source_dir")"
fi

cat > "$output_dir/SOURCE.txt" <<EOF
Native Windows agbcc and old_agbcc (PE32, i686 MinGW).
Upstream: https://github.com/pret/agbcc
Revision: $revision
No compiler source patches. See source/build-agbcc.sh for the build recipe.
The complete upstream corresponding source and GPL licenses are included.
Headers are copied from this revision's libc/include and ginclude directories.
These standalone compiler frontends compile preprocessed C to Thumb assembly.
Preprocessing and assembling use the separately installed Arm GNU toolchain.
EOF

python3 - "$output_dir" <<'PY'
from pathlib import Path
import sys
import zipfile

root = Path(sys.argv[1])
archive = root.with_suffix('.zip')
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
    for path in sorted(root.rglob('*')):
        if path.is_file():
            out.write(path, path.relative_to(root).as_posix())
print(archive)
PY
