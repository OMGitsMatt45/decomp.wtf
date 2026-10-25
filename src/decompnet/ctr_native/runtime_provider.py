"""Pinned, source-shipped 3DS kernel/service/PICA runtime.

The downloaded trees stay immutable. Integration patches apply only to the
freshly generated owner's project; no installed emulator is invoked.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

from ..pc import PCError
from . import provider

COMMIT = 'e174910de5e7285581b153cbce05543efb135cd5'
ARCHIVE_SHA256 = 'a1702de000f34d4ef397287911402b66967b98eac741e7027f402835f6b050cb'
SOURCE_SHA256 = 'de45e596cca50d5439553aad5c3a0f7a2799b6a6dcd52e884211e2cc9257c6d1'
URL = f'https://codeload.github.com/fearkov/zakuro/tar.gz/{COMMIT}'


def download(destination, *, archive=None, recompiler=None):
    destination = Path(destination)
    if destination.exists():
        raise PCError('3DS runtime destination exists; preserve its source')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ctr-runtime-', dir=destination.parent) as temp:
        work = Path(temp)
        packed = work/'runtime.tar.gz'
        if archive:
            shutil.copyfile(archive, packed)
        else:
            with urllib.request.urlopen(URL, timeout=90) as response, packed.open('wb') as out:
                total = 0
                while block := response.read(1024*1024):
                    total += len(block)
                    if total > 16*1024*1024:
                        raise PCError('3DS runtime archive exceeds its download bound')
                    out.write(block)
        with packed.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != ARCHIVE_SHA256:
                raise PCError('3DS runtime archive checksum differs')
        unpack = work/'unpack'
        with tarfile.open(packed) as tar:
            if sum(m.size for m in tar.getmembers()) > 96*1024*1024:
                raise PCError('3DS runtime unpacked source exceeds its bound')
            tar.extractall(unpack, filter='data')
        original = unpack/('zakuro-'+COMMIT)
        source = work/'source'
        runtime = source/'runtime'
        runtime.mkdir(parents=True)
        for name in ('Cargo.toml','Cargo.lock','LICENSE'):
            shutil.copyfile(original/name, runtime/name)
        shutil.copytree(original/'crates', runtime/'crates')
        if provider.fingerprint(runtime) != SOURCE_SHA256:
            raise PCError('3DS runtime source fingerprint differs')
        if recompiler:
            provider.verify(recompiler)
            shutil.copytree(recompiler, source/'recompiler')
        else:
            provider.download(source/'recompiler')
        verify(source)
        source.rename(destination)
    return destination


def verify(source):
    source = Path(source)
    if provider.fingerprint(source/'runtime') != SOURCE_SHA256:
        raise PCError('3DS runtime sources changed; preserve edits and choose a clean runtime SDK')
    provider.verify(source/'recompiler')
    return dict(runtime_commit=COMMIT, runtime_source_sha256=SOURCE_SHA256,
                recompiler_commit=provider.COMMIT, recompiler_source_sha256=provider.SOURCE_SHA256)
