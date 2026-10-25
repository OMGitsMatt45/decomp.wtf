"""Pinned source-only PS2 runtime package, kept separate from owner game data.

The graphics package contributes its generic GS implementation. Game launchers,
address maps, icons and gameplay hooks are not selected from that repository.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

from ..pc import PCError

INPUTS = Path(__file__).with_name('runtime-inputs.json')


def payload(root):
    root = Path(root)
    return sorted((p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                   and p.suffix != '.pyc' and p.name != '.decompnet-toolchain.json'),
                  key=lambda p: p.relative_to(root).as_posix())


def fingerprint(root):
    root = Path(root); digest = hashlib.sha256()
    for path in payload(root):
        if path.is_symlink(): raise PCError('PS2 runtime source contains a symbolic link')
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def download(destination: Path, *, log=None, archives: Path | None = None):
    destination = Path(destination).resolve()
    if destination.exists(): raise PCError('PS2 runtime destination exists; preserve existing source')
    pins = json.loads(INPUTS.read_text(encoding='utf-8'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ps2-runtime-', dir=destination.parent) as temporary:
        stage = Path(temporary); source = stage / 'source'; source.mkdir()
        for number, item in enumerate(pins['archives']):
            if log: log('Fetching pinned PS2 ' + item['name'] + ' source...')
            archive = stage / f'{number}.tar.gz'
            if archives is not None:
                shutil.copyfile(Path(archives) / (item['name'] + '.tar.gz'), archive)
            else:
                with urllib.request.urlopen(item['url'], timeout=60) as response, archive.open('wb') as out:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 64 * 1024 * 1024: raise PCError('PS2 runtime archive exceeds its download bound')
                        out.write(chunk)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != item['sha256']:
                raise PCError('PS2 runtime archive checksum differs: ' + item['name'])
            unpack = stage / f'unpack-{number}'; unpack.mkdir()
            with tarfile.open(archive) as tar: tar.extractall(unpack, filter='data')
            trees = list(unpack.iterdir())
            if len(trees) != 1 or not trees[0].is_dir(): raise PCError('PS2 source archive layout differs')
            for copy in item['copy']:
                original, target = trees[0] / copy['source'], source / copy['target']
                if original.is_dir(): shutil.copytree(original, target, dirs_exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(original, target)
        actual = fingerprint(source)
        if not pins['source_sha256'] or actual != pins['source_sha256']:
            raise PCError('PS2 runtime sources differ from the pinned package')
        source.rename(destination)
    return dict(path=str(destination), source_sha256=actual)


def verify(source):
    pins = json.loads(INPUTS.read_text(encoding='utf-8'))
    if not pins['source_sha256'] or fingerprint(source) != pins['source_sha256']:
        raise PCError('PS2 runtime source differs from the pinned package; restore its source')
    return pins
