"""Export a verified, editable host runtime without installing donor binaries."""
import hashlib
import json
from pathlib import Path
import shutil

from ... import pc
from . import patches

ROOT = Path(__file__).parent


def verify():
    source = ROOT.parent / 'vendor/kirikae-src'
    manifest = json.loads((ROOT / 'runtime-sources.json').read_text())
    paths = list(source.rglob('*'))
    if any(p.is_symlink() for p in paths) or {p.relative_to(source).as_posix() for p in paths if p.is_file()} != set(manifest['files']):
        raise pc.PCError('Switch runtime source inventory differs from its pin')
    for name, digest in manifest['files'].items():
        path = source / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise pc.PCError('Switch runtime source differs from its pin: ' + name)
    return source


def export(destination):
    shutil.copytree(verify(), destination)
    for name in ('Cargo.toml', 'Cargo.lock'):
        shutil.copyfile(ROOT / name, destination / name)
    patches.runtime(destination, ROOT)
