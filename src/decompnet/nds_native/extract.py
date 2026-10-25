"""Standalone, exact-input asset staging. No BIOS or mobile assets are used."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    if len(sys.argv) != 2:
        raise ValueError('usage: python tools/extract_assets.py original.nds')
    root = Path(__file__).resolve().parent.parent
    identity = json.loads((root/'game/input.json').read_text(encoding='utf-8'))
    original = Path(sys.argv[1]).resolve()
    with original.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != identity['sha256']:
        raise ValueError('original ROM SHA-256 differs from the translated input')
    target = root/'assets/game.nds'
    target.parent.mkdir(exist_ok=True)
    if target.resolve() == original:
        raise ValueError('input must be outside the generated assets directory')
    temporary = target.with_suffix('.tmp')
    created=False
    try:
        with temporary.open('xb') as output, original.open('rb') as source:
            created=True
            shutil.copyfileobj(source,output)
            for patch in identity.get('asset_patches',[]):
                value=bytes.fromhex(patch['hex']);start=patch['offset']
                if type(start) is not int or not 0<=start<start+len(value)<=identity['size']:
                    raise ValueError('decoded asset patch exceeds original input')
                output.seek(start);output.write(value)
        with temporary.open('rb') as stream:
            verified=hashlib.sha256()
            for chunk in iter(lambda:stream.read(1024*1024),b''):verified.update(chunk)
        if verified.hexdigest()!=identity['asset_sha256']:
            raise ValueError('staged DS asset SHA-256 differs from decoded identity')
        temporary.replace(target)
    except Exception:
        if created:temporary.unlink(missing_ok=True)
        raise
    print('Staged the exact DS assets; no BIOS, firmware or mobile OBB is needed')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print('asset extraction: '+str(error),file=sys.stderr)
        sys.exit(1)
