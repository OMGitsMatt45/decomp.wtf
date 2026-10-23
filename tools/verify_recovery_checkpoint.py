#!/usr/bin/env python3
"""Verify a private recovery ZIP against its public, hash-only checkpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile


def digest(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(checkpoint: Path, archive: Path) -> int:
    expected = json.loads(checkpoint.read_text())['private_checkpoint']
    if archive.stat().st_size != expected['bytes']:
        raise ValueError('archive size differs from the checkpoint')
    with archive.open('rb') as stream:
        if digest(stream) != expected['sha256']:
            raise ValueError('archive SHA-256 differs from the checkpoint')
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate ZIP members')
        raw_index = bundle.read('INDEX.json')
        if hashlib.sha256(raw_index).hexdigest() != expected['index_sha256']:
            raise ValueError('index SHA-256 differs from the checkpoint')
        entries = json.loads(raw_index)['files']
        paths = [item['path'] for item in entries]
        if len(paths) != len(set(paths)) or len(paths) != expected['member_count']:
            raise ValueError('duplicate or missing indexed members')
        if set(names) != set(paths) | {'INDEX.json'}:
            raise ValueError('ZIP members differ from the index')
        for item in entries:
            info = bundle.getinfo(item['path'])
            if info.file_size != item['bytes']:
                raise ValueError('member size differs: '+item['path'])
            with bundle.open(info) as stream:
                if digest(stream) != item['sha256']:
                    raise ValueError('member SHA-256 differs: '+item['path'])
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--checkpoint', type=Path,
        default=Path(__file__).resolve().parents[1]/'recovery/syphon-filter/checkpoint.json')
    args = parser.parse_args()
    try:
        count = verify(args.checkpoint, args.archive)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print('Verification failed: '+str(error), file=sys.stderr)
        return 1
    print(f'Verified archive, index and {count} members. No files extracted or modified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
