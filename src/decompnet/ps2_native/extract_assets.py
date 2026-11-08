"""Stage owner media for this standalone project. Python standard library only."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


def _asset_name(path):
    name = PurePosixPath(path)
    if (not name.parts or name.is_absolute() or any(p in ('.', '..') for p in name.parts)
            or '\\' in path or ':' in path):
        raise ValueError('asset path escapes its disc')
    return name


def _stage_image(original, assets, recipe, reference):
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    before = original.stat()
    image = original if reference else assets/('disc.img' if recipe['kind']=='disc' else 'boot.elf')
    digest = hashlib.sha256()
    with original.open('rb') as source:
        if reference:
            while chunk := source.read(4*1024*1024):
                digest.update(chunk)
            (assets/'disc.path').write_text(str(original)+'\n', encoding='utf-8')
        else:
            with image.open('xb') as target:
                while chunk := source.read(4*1024*1024):
                    digest.update(chunk)
                    target.write(chunk)
    if digest.hexdigest()!=recipe['input']['sha256'] or image.stat().st_size!=recipe['input']['size']:
        raise ValueError('original input differs from the SHA-256 recorded at export')
    if identity(original.stat())!=identity(before):
        raise ValueError('owner input changed while staging')
    cd=assets/'cd'
    cd.mkdir()
    if recipe['kind']=='disc':
        sector,skip=recipe['sector_size'],recipe['sector_data_offset']
        with image.open('rb') as source:
            for row in recipe['extract']:
                out=cd/_asset_name(row['path'])
                out.parent.mkdir(parents=True,exist_ok=True)
                remaining=row['size']
                block=row['lba']
                total=hashlib.sha256()
                with out.open('xb') as target:
                    while remaining:
                        n=min(2048,remaining)
                        source.seek(block*sector+skip)
                        chunk=source.read(n)
                        if len(chunk)!=n:
                            raise ValueError('truncated asset extent')
                        target.write(chunk)
                        total.update(chunk)
                        remaining-=n
                        block+=1
                if total.hexdigest()!=row['sha256']:
                    raise ValueError('extracted asset hash differs: '+row['path'])
    else:
        shutil.copyfile(image,cd/'boot.elf')
    if identity(original.stat())!=identity(before):
        raise ValueError('owner input changed while staging')


def _stage_directory(original, assets, recipe):
    directory = recipe.get('directory')
    if (recipe['kind'] != 'disc' or recipe.get('sector_size') != 2048
            or recipe.get('sector_data_offset') != 0 or recipe.get('disc_medium') != 'dvd'
            or not directory or not directory['files']):
        raise ValueError('export has no verified extracted DVD file inventory')
    sectors = directory['sectors']
    if type(sectors) is not int or not 0 < sectors <= 0xffffffff or sectors * 2048 != recipe['input']['size']:
        raise ValueError('invalid extracted DVD sector count')
    if not original.is_dir():
        raise ValueError('extracted DVD input must be a directory')
    cd = assets/'cd'
    cd.mkdir()
    for row in directory['files']:
        name = _asset_name(row['path'])
        candidate = original/name
        try:
            source = candidate.resolve(strict=True)
        except FileNotFoundError:
            # ISO 9660's extension separator may be omitted during extraction.
            if not name.name.endswith('.'):
                raise
            source = candidate.with_name(name.name[:-1]).resolve(strict=True)
        if not source.is_relative_to(original) or not source.is_file():
            raise ValueError('extracted asset must be a file inside its source directory: '+str(name))
        size = row['size']
        if source.stat().st_size != size:
            raise ValueError('extracted asset size differs: '+str(name))
        out = cd/name
        out.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open('rb') as stream, out.open('xb') as target:
            remaining = size
            while remaining:
                chunk = stream.read(min(4*1024*1024, remaining))
                if not chunk:
                    raise ValueError('truncated extracted asset: '+str(name))
                digest.update(chunk)
                target.write(chunk)
                remaining -= len(chunk)
            if stream.read(1) or digest.hexdigest() != row['sha256']:
                raise ValueError('extracted asset hash differs: '+str(name))
    (assets/'disc.directory').write_bytes(f'{sectors}\n'.encode('ascii'))


def stage(original, root, *, reference=False, directory=False):
    original, root = Path(original).resolve(), Path(root).resolve()
    recipe = json.loads((root/'game/assets.json').read_text(encoding='utf-8'))
    if recipe['schema'] != 'decomp.wtf.ps2-assets/v1':
        raise ValueError('unsupported asset recipe')
    destination = root/'assets'
    if destination.exists():
        raise ValueError('assets already exist; preserve your current assets and saves')
    if reference and directory:
        raise ValueError('choose either a disc reference or an extracted directory')
    if reference and recipe['kind'] != 'disc':
        raise ValueError('external asset references require a disc image')
    if reference and any(c in str(original) for c in '\r\n'):
        raise ValueError('external disc paths cannot contain line breaks')
    with tempfile.TemporaryDirectory(prefix='.ps2-assets-', dir=root) as temporary:
        assets = Path(temporary)/'assets'
        assets.mkdir()
        identity = dict(recipe['input'])
        if directory:
            _stage_directory(original, assets, recipe)
            identity['staged_media'] = 'directory'
        else:
            _stage_image(original, assets, recipe, reference)
        (assets/'identity.json').write_text(json.dumps(identity, indent=2)+'\n', encoding='utf-8')
        if destination.exists():
            raise ValueError('asset destination appeared during staging')
        assets.rename(destination)
    return destination


if __name__=='__main__':
    try:
        args = sys.argv[1:]
        reference, directory = '--reference' in args, '--directory' in args
        if reference:
            args.remove('--reference')
        if directory:
            args.remove('--directory')
        if len(args) != 1:
            raise ValueError('usage: python tools/extract_assets.py [--reference | --directory] ORIGINAL_MEDIA')
        print(stage(args[0], Path(__file__).resolve().parents[1], reference=reference, directory=directory))
    except (OSError, ValueError, KeyError) as error:
        print('error: '+str(error), file=sys.stderr)
        sys.exit(1)
