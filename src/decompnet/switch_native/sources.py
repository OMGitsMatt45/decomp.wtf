"""Pull all pinned Switch donor trees for editing and comparison builds.

The application emitter is vendored and builds offline. This separate tool
fetches the complete donor workspaces; it never runs upstream setup scripts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import urllib.request

from ..pc import PCError
from .provider import sources


def pull(destination, donor):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (donor['id'] + '.tar.gz')
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=destination, prefix='.download-', delete=False) as stream:
            temp = Path(stream.name)
            try:
                with urllib.request.urlopen(donor['url'], timeout=60) as response:
                    count = 0
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > 128 * 1024 * 1024:
                            raise PCError('Switch donor archive exceeds its bound')
                        stream.write(chunk)
                stream.close()
                if hashlib.sha256(temp.read_bytes()).hexdigest() != donor['archive_sha256']:
                    raise PCError('Switch donor archive checksum differs: ' + donor['id'])
                temp.rename(archive)
            finally:
                temp.unlink(missing_ok=True)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != donor['archive_sha256']:
            raise PCError('Switch cached donor checksum differs: ' + donor['id'])
    target = destination / donor['id']
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        prefixes = {m.name.split('/')[0] for m in members}
        if len(prefixes) != 1 or sum(m.size for m in members) > 512 * 1024 * 1024:
            raise PCError('Switch donor source layout exceeds its bound')
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise PCError('Switch donor archive must contain only directories and regular files')
        prefix = prefixes.pop()
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=destination, prefix='.unpack-') as work:
                tar.extractall(work, filter='data')
                (Path(work) / prefix).rename(target)
        # Never replace a developer's modified checkout on a second pull.
        for member in members:
            if member.isfile():
                relative = Path(member.name).relative_to(prefix)
                path = target / relative
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(target.resolve()):
                    raise PCError('Switch donor source missing or external: ' + str(path))
                with tar.extractfile(member) as original, path.open('rb') as current:
                    if hashlib.file_digest(original, 'sha256').digest() != hashlib.file_digest(current, 'sha256').digest():
                        raise PCError('Switch donor source has edits; preserved: ' + str(path))
    return dict(id=donor['id'], path=str(target.resolve()), commit=donor['commit'],
                archive_sha256=donor['archive_sha256'], verified=True)


def main(argv=None):
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda d: pull(args.destination, d), sources()['donors']))
        print(json.dumps(dict(schema='decomp.wtf.switch-source-pull/v1', sources=results), indent=2))
        return 0
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
