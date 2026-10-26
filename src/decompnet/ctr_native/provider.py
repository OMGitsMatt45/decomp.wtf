"""Pinned source-only ARM11 emitter; Rust is needed only at export time."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from ..pc import PCError

COMMIT = 'cec1270db38411f9c02d3f356fc3ed6c3f007424'
ARCHIVE_SHA256 = 'c135bf2971ececad71eab4cb991002b977f82494165743d3f50949b308e3d110'
URL = f'https://codeload.github.com/fearkov/3dsrecomp/tar.gz/{COMMIT}'


def fingerprint(root):
    value = hashlib.sha256()
    for path in sorted(Path(root).rglob('*'), key=lambda p:p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PCError('3DS emitter source contains a symbolic link')
        if path.is_file():
            value.update(path.relative_to(root).as_posix().encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    return value.hexdigest()


def download(destination, *, archive=None):
    destination = Path(destination)
    if destination.exists():
        raise PCError('3DS emitter destination exists; preserve existing source')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ctr-source-', dir=destination.parent) as temp:
        temp = Path(temp)
        packed = temp/'source.tar.gz'
        if archive is not None:
            shutil.copyfile(archive, packed)
        else:
            with urllib.request.urlopen(URL, timeout=60) as response, packed.open('wb') as out:
                count = 0
                while chunk := response.read(1024*1024):
                    count += len(chunk)
                    if count > 4*1024*1024:
                        raise PCError('3DS emitter source archive exceeds its bound')
                    out.write(chunk)
        if hashlib.sha256(packed.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise PCError('3DS emitter source archive checksum differs')
        unpack = temp/'unpack'
        with tarfile.open(packed) as tar:
            if sum(m.size for m in tar.getmembers()) > 8*1024*1024:
                raise PCError('3DS emitter unpacked source exceeds its bound')
            tar.extractall(unpack, filter='data')
        source = unpack/('3dsrecomp-'+COMMIT)
        if fingerprint(source) != SOURCE_SHA256:
            raise PCError('3DS emitter source fingerprint differs')
        source.rename(destination)
    return destination


# Fingerprint of every file in the verified upstream archive, excluding Git metadata.
SOURCE_SHA256 = '41a3d061aa03a9cdaa5037ee0cf3278bec7a8b76649421d08a587ad80455c39e'


def verify(source):
    if fingerprint(source) != SOURCE_SHA256:
        raise PCError('3DS emitter source changed; preserve edits and choose a clean SDK directory')


def _run(command, *, cwd=None, timeout=180):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PCError('3DS emitter compiler could not run: '+str(error)) from error
    if result.returncode:
        raise PCError('3DS emitter compilation failed:\n'+result.stderr[-6000:])
    return result.stdout


def build(source, destination, rustc):
    verify(source)
    destination = Path(destination)
    adapter = Path(__file__).with_name('emitter.rs')
    version = _run([str(rustc), '--version'], timeout=15).strip()
    match = re.search(r'rustc (\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (1,88):
        raise PCError('3DS source generation requires Rust 1.88+: https://www.rust-lang.org/tools/install')
    key = hashlib.sha256((SOURCE_SHA256+version).encode()+adapter.read_bytes()).hexdigest()
    binary = destination/('ctr-emitter.exe' if __import__('os').name=='nt' else 'ctr-emitter')
    marker = destination/'build.json'
    if binary.is_file() and marker.is_file():
        data = json.loads(marker.read_text())
        if data == dict(key=key, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest()):
            return binary
        raise PCError('3DS emitter build cache differs; choose a clean cache and preserve edits')
    if destination.exists():
        raise PCError('3DS emitter build directory is incomplete; preserve it and choose a new cache')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ctr-build-', dir=destination.parent) as temp:
        work = Path(temp)
        shutil.copytree(source, work/'sdk')
        shutil.copyfile(adapter, work/'emitter.rs')
        for args in ([str(rustc), '--edition=2021', '--crate-name', 'recomp_abi', '--crate-type=rlib',
                      'sdk/abi/src/lib.rs', '-O', '-o', 'librecomp_abi.rlib'],
                     [str(rustc), '--edition=2021', 'emitter.rs', '--extern', 'recomp_abi=librecomp_abi.rlib',
                      '-O', '-A', 'dead_code', '-o', binary.name]):
            _run(args, cwd=work)
        shutil.rmtree(work/'sdk')
        (work/'emitter.rs').unlink()
        (work/'librecomp_abi.rlib').unlink()
        (work/'build.json').write_text(json.dumps(dict(key=key, binary_sha256=hashlib.sha256((work/binary.name).read_bytes()).hexdigest())))
        work.rename(destination)
    return binary
