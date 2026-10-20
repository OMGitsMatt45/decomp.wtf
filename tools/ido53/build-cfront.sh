#!/usr/bin/env bash
# Build an optional classic cfront overlay, preserving the installed 5.3 backend.
# Usage: build-cfront.sh BUILD_DIRECTORY OUTPUT_DIRECTORY
set -euo pipefail
build_dir=$(mkdir -p "$1" && cd "$1" && pwd)
out_dir=$(mkdir -p "$2" && cd "$2" && pwd)
recipe_dir=$(cd "$(dirname "$0")" && pwd)
revision=d5aec59932034b8a20f23f471297a55c45dcbc45
git -c core.autocrlf=false clone https://github.com/decompals/ido-static-recomp.git "$build_dir/source"
cd "$build_dir/source"
git config core.autocrlf false
git checkout --detach "$revision"
git apply "$recipe_dir/native-cfront.patch"
cp "$recipe_dir/cfront_host.h" .
make -j2 RELEASE=1 setup
make -j2 RELEASE=1 VERSION=5.3 IDO_TC='CC cfront ptcomp markc++ ptlink' LDFLAGS='-static-libgcc -lm'
platform=linux-x86_64
suffix=
if [[ ${OS:-} == Windows_NT ]]; then platform=windows-x86_64; suffix=.exe; fi
package="$build_dir/package"
mkdir -p "$package"
cp "build/5.3/out/CC$suffix" "$package/classic-CC$suffix"
for name in cfront ptcomp markc++ ptlink; do cp "build/5.3/out/$name$suffix" "$package/"; done
python - "$package" "$revision" "$platform" <<'PY'
import hashlib, json
from pathlib import Path
import sys
package, revision, platform = sys.argv[1:]
inputs = ['usr/lib/CC', 'usr/lib/c++/cfront', 'usr/lib/c++/ptcomp', 'usr/lib/c++/markc++', 'usr/lib/c++/ptlink']
manifest = {'format': 1, 'frontend': 'cfront', 'toolchain': 'ido-5.3', 'upstream_revision': revision,
            'platform': platform, 'irix_inputs': {p: hashlib.sha256((Path('ido/5.3') / p).read_bytes()).hexdigest() for p in inputs}}
(Path(package) / 'cfront-build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
PY
cp "$recipe_dir/build-cfront.sh" "$recipe_dir/native-cfront.patch" .
tar --exclude=.git --exclude=build --exclude=tools/rabbitizer/build \
    -czf "$out_dir/ido53-cfront-$platform-source-v1.tar.gz" .
tar -czf "$out_dir/ido53-cfront-$platform-v1.tar.gz" -C "$package" .
(cd "$out_dir" && sha256sum ido53-cfront-*.tar.gz > SHA256SUMS)
