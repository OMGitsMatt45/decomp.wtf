"""Read owner-supplied PS1 programs and ordered media without a matching compiler."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct

from .. import pc
from ..rom import chd, psx, psx_media
from . import module_discovery


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def expand(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    result=[]
    for value in paths:
        path=Path(value).resolve()
        if path.suffix.lower()=='.m3u':
            if path.stat().st_size>1<<20:raise pc.PCError('disc playlists must be at most 1 MiB')
            entries=[line.strip() for line in path.read_text(encoding='utf-8-sig').splitlines()
                     if line.strip() and not line.lstrip().startswith('#')]
            if any(Path(name).suffix.lower()=='.m3u' for name in entries):raise pc.PCError('nested disc playlists are unsupported')
            result.extend((path.parent/name).resolve() for name in entries)
        else:result.append(path)
    if not 1<=len(result)<=16:raise pc.PCError('provide one to sixteen discs in game order')
    if len(set(result))!=len(result):raise pc.PCError('the same disc cannot appear twice')
    return result


@contextmanager
def reader(path,media):
    primary=path.parent/media['primary'] if media else path
    if path.suffix.lower()=='.chd':
        stream=chd.Chd(path)
        try:yield stream
        finally:stream.close()
    elif media:
        with psx_media.decoded(primary,media) as stream:yield stream
    else:
        with primary.open('rb') as stream:yield stream


def read(path,index):
    with path.open('rb') as stream:head=stream.read(8)
    media=psx_media.cue(path) if path.suffix.lower()=='.cue' else None
    files=[dict(source='',name=path.name,sha256=sha(path),size=path.stat().st_size)]
    if media:
        # cue() validates relative paths, track ordering, bounds and sector geometry.
        names=[media['primary'],*[item['name'] for item in media['companions'] if item['name']!=path.name]]
        for name in names:
            source=psx_media.inside(path.parent,name)
            files.append(dict(source=name,name=name,sha256=sha(source),size=source.stat().st_size))
    modules=[]
    if head==b'PS-X EXE':
        raw=path.read_bytes();boot='PSX.EXE';kind='exe'
    else:
        with reader(path,media) as source:
            raw,boot,platform=psx.from_disc(source)
            if platform!='psx':raise pc.PCError('this disc contains a PS2 program; use the PS2 backend')
            psx.read_exe(raw,boot)  # Validate the boot program before optional discovery.
            modules=module_discovery.discover(source,raw)
        kind='disc'
    image,info=psx.read_exe(raw,boot)
    # Content identity ignores cue spelling/comments, retaining all actual tracks.
    hashes=[item['sha256'] for item in files if item['source']] if media else [files[0]['sha256']]
    identity=hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
    asset='PSX.ISO' if kind=='exe' else path.name
    return dict(index=index,path=path,files=files,kind=kind,identity=identity,
                image=image,info=info,boot=boot,modules=modules,asset=f'assets/disc{index}/{asset}')


def prepare(paths):
    discs=[read(path,i+1) for i,path in enumerate(expand(paths))]
    if len({disc['identity'] for disc in discs})!=len(discs):raise pc.PCError('the same disc content cannot appear twice')
    return discs


def project_input(project,index):
    """Read a retained import without reconstructing or modifying its CUE tracks."""
    root=Path(project['root']);layout=project.get('psx_disc')
    if not layout:
        source=project.get('rom',{}).get('file')
        if not source:raise pc.PCError('this project has no retained PS1 input; generate from the original disc')
        return read(root/source,index)
    original=root/layout['file'];container=layout.get('media')
    if container:psx_media.verify_files(original,layout)
    elif sha(original)!=layout['sha256']:raise pc.PCError('the retained PS1 disc hash differs')
    def reviewed(source):
        from ..rom.psx_layout import read_map
        modules=[]
        for mapping in layout.get('maps',[]):
            if mapping.get('load') is None:continue
            raw=read_map(psx._Disc(source),mapping)
            if hashlib.sha256(raw).hexdigest()!=mapping['sha256']:
                raise pc.PCError('reviewed PS1 module hash differs: '+mapping['segment'])
            if raw[:8]==b'PS-X EXE':image,info=psx.read_exe(raw,mapping['segment'])
            else:
                meta=project.get('psx_modules',{}).get(mapping['segment'],{})
                start=meta.get('code_start',mapping.get('code_at',0));end=meta.get('code_end',len(raw))
                if not 0<=start<end<=len(raw) or start%4 or end%4:
                    raise pc.PCError('reviewed PS1 module code bounds differ')
                header=bytearray(2048);header[:8]=b'PS-X EXE'
                struct.pack_into('<4I',header,0x10,mapping['load']+start,meta.get('gp',0),mapping['load'],len(raw))
                image,info=psx.read_exe(bytes(header)+raw,mapping['segment'])
                info.update(code_start=start,code_end=end)
            modules.append(dict(index=index,image=image,info=info,boot=mapping['segment']+'.EXE'))
        return modules
    def programs(source, raw):
        modules=reviewed(source)
        identities={hashlib.sha256(module['image']).digest() for module in modules}
        identities.add(hashlib.sha256(raw).digest())
        for module in module_discovery.discover(source,raw):
            identity=hashlib.sha256(module['image']).digest()
            if identity not in identities:
                identities.add(identity);modules.append(module)
        return modules
    if container:
        with psx_media.decoded(original,container) as stream:
            raw,boot,platform=psx.from_disc(stream)
            modules=programs(stream,raw)
    else:
        with original.open('rb') as stream:
            raw,boot,platform=psx.from_disc(stream);modules=programs(stream,raw)
    if platform!='psx':raise pc.PCError('this is a PS2 disc, not a PS1 game')
    image,info=psx.read_exe(raw,boot)
    if container and container['kind']=='cue':
        cue=next((item for item in container['companions'] if item['name'].lower().endswith('.cue')),None)
        if cue is None:raise pc.PCError('the retained CUE sheet is missing')
        path=root/container['directory']/cue['name']
        files=[dict(source='',**cue),dict(source=container['primary'],name=container['primary'],
                    sha256=layout['sha256'],size=layout['original_size'])]
        files.extend(dict(source=item['name'],**item) for item in container['companions'] if item is not cue)
        hashes=[item['sha256'] for item in files[1:]]
    else:
        path=original;files=[dict(source='',name=path.name,sha256=sha(path),size=path.stat().st_size)]
        hashes=[files[0]['sha256']]
    return dict(index=index,path=path,files=files,kind='disc',image=image,info=info,boot=boot,modules=modules,
                identity=hashlib.sha256(json.dumps(hashes).encode()).hexdigest(),asset=f'assets/disc{index}/{path.name}')
