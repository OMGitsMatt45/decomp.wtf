"""Stage owner media for this standalone project. Python standard library only."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile


def stage(original,root,*,reference=False):
    original,root=Path(original).resolve(),Path(root).resolve()
    recipe=json.loads((root/'game/assets.json').read_text(encoding='utf-8'))
    if recipe['schema']!='decomp.wtf.ps2-assets/v1':raise ValueError('unsupported asset recipe')
    destination=root/'assets'
    if destination.exists():raise ValueError('assets already exist; preserve your current assets and saves')
    before=original.stat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if reference and recipe['kind']!='disc':raise ValueError('external asset references require a disc image')
    if reference and any(c in str(original) for c in '\r\n'):raise ValueError('external disc paths cannot contain line breaks')
    with tempfile.TemporaryDirectory(prefix='.ps2-assets-',dir=root) as temporary:
        work=Path(temporary);assets=work/'assets';assets.mkdir()
        image=original if reference else assets/('disc.img' if recipe['kind']=='disc' else 'boot.elf')
        digest=hashlib.sha256()
        if reference:
            with original.open('rb') as source:
                while chunk:=source.read(4*1024*1024):digest.update(chunk)
            (assets/'disc.path').write_text(str(original)+'\n',encoding='utf-8')
        else:
            with original.open('rb') as source,image.open('xb') as target:
                while chunk:=source.read(4*1024*1024):digest.update(chunk);target.write(chunk)
        if digest.hexdigest()!=recipe['input']['sha256'] or image.stat().st_size!=recipe['input']['size']:
            raise ValueError('original input differs from the SHA-256 recorded at export')
        if identity(original.stat())!=identity(before):raise ValueError('owner input changed while staging')
        cd=assets/'cd';cd.mkdir()
        if recipe['kind']=='disc':
            sector,skip=recipe['sector_size'],recipe['sector_data_offset']
            with image.open('rb') as source:
                for row in recipe['extract']:
                    name=PurePosixPath(row['path'])
                    if name.is_absolute() or any(p in ('.','..') for p in name.parts) or '\\' in str(name) or ':' in str(name):
                        raise ValueError('asset path escapes its disc')
                    out=cd/name;out.parent.mkdir(parents=True,exist_ok=True)
                    remaining=row['size'];block=row['lba'];total=hashlib.sha256()
                    with out.open('xb') as target:
                        while remaining:
                            n=min(2048,remaining);source.seek(block*sector+skip);chunk=source.read(n)
                            if len(chunk)!=n:raise ValueError('truncated asset extent')
                            target.write(chunk);total.update(chunk);remaining-=n;block+=1
                    if total.hexdigest()!=row['sha256']:raise ValueError('extracted asset hash differs: '+str(name))
        else:shutil.copyfile(image,cd/'boot.elf')
        (assets/'identity.json').write_text(json.dumps(recipe['input'],indent=2)+'\n',encoding='utf-8')
        if identity(original.stat())!=identity(before):raise ValueError('owner input changed while staging')
        if destination.exists():raise ValueError('asset destination appeared during staging')
        assets.rename(destination)
    return destination


if __name__=='__main__':
    try:
        args=sys.argv[1:];reference='--reference' in args
        if reference:args.remove('--reference')
        if len(args)!=1:raise ValueError('usage: python tools/extract_assets.py [--reference] ORIGINAL_ISO_BIN_OR_ELF')
        print(stage(args[0],Path(__file__).resolve().parents[1],reference=reference))
    except (OSError,ValueError,KeyError) as error:
        print('error: '+str(error),file=sys.stderr);sys.exit(1)
