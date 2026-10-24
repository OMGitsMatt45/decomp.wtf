"""Stage the original ordered disc set for this generated source repository.

Run: python tools/extract_assets.py /path/to/disc1.cue /path/to/disc2.cue
Only Python's standard library is required. Existing assets and saves are preserved.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import tempfile


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def iso(program):
    """An original ISO9660 envelope for an owner-provided standalone PS-X EXE."""
    def both16(n):return struct.pack('<H',n)+struct.pack('>H',n)
    def both32(n):return struct.pack('<I',n)+struct.pack('>I',n)
    def record(name,lba,size,directory=False):
        value=b'\0\0'+both32(lba)+both32(size)+bytes(7)+bytes([2 if directory else 0,0,0])+both16(1)+bytes([len(name)])+name
        value+=bytes(len(value)%2)
        return bytes([len(value)])+value[1:]
    files={'SYSTEM.CNF':b'BOOT = cdrom:\\PSX.EXE;1\r\n','PSX.EXE':program}
    lba=20;places={}
    for name,data in files.items():places[name]=(lba,len(data));lba+=(len(data)+2047)//2048
    root=record(b'\0',19,2048,True)+record(b'\1',19,2048,True)
    for name,(start,size) in places.items():root+=record((name+';1').encode(),start,size)
    pvd=bytearray(2048);pvd[:7]=b'\x01CD001\x01';pvd[8:40]=b'PLAYSTATION'.ljust(32,b' ')
    pvd[40:72]=b'ORIGINAL_PROGRAM'.ljust(32,b' ');pvd[80:88]=both32(lba)
    pvd[120:124]=both16(1);pvd[124:128]=both16(1);pvd[128:132]=both16(2048)
    pvd[156:190]=record(b'\0',19,2048,True);pvd[881]=1
    image=bytearray(16*2048)+pvd+bytearray(b'\xffCD001\x01'.ljust(2048,b'\0'))+bytearray(2048)+root.ljust(2048,b'\0')
    for data in files.values():image+=data+bytes(-len(data)%2048)
    return bytes(image)


def inside(folder,name):
    rel=PurePosixPath(name)
    if rel.is_absolute() or any(p in ('..','.') or ':' in p for p in rel.parts) or '\\' in name:
        raise ValueError('asset recipe contains an external path')
    target=folder.joinpath(*rel.parts)
    if not target.resolve().is_relative_to(folder.resolve()):raise ValueError('asset path leaves its input directory')
    return target


def stage(root,inputs):
    expanded=[]
    for value in inputs:
        path=Path(value).resolve()
        if path.suffix.lower()=='.m3u':
            if path.stat().st_size>1<<20:raise ValueError('disc playlist exceeds 1 MiB')
            names=[line.strip() for line in path.read_text(encoding='utf-8-sig').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
            if any(Path(name).suffix.lower()=='.m3u' for name in names):raise ValueError('nested disc playlists are unsupported')
            expanded.extend(path.parent/name for name in names)
        else:expanded.append(path)
    inputs=expanded
    recipe=json.loads((root/'game/assets.json').read_text(encoding='utf-8'))
    if len(inputs)!=len(recipe['discs']):raise ValueError('provide every original disc in the recorded order')
    checked=[]
    for disc,value in zip(recipe['discs'],inputs):
        path=Path(value).resolve()
        rows=[]
        for item in disc['files']:
            source=inside(path.parent,item['source']) if item['source'] else path
            if source.stat().st_size!=item['size'] or digest(source)!=item['sha256']:
                raise ValueError(f'disc {disc["index"]}: original input/track hash differs; check disc order')
            rows.append((source,item['name']))
        checked.append((disc,rows))
    target=root/'assets'
    if target.exists():raise ValueError('assets already exist; choose a new directory or preserve/move them before restaging')
    with tempfile.TemporaryDirectory(prefix='.psx-assets-',dir=root) as temp:
        work=Path(temp)/'assets';work.mkdir()
        for disc,rows in checked:
            folder=work/f'disc{disc["index"]}';folder.mkdir()
            if disc['kind']=='exe':(folder/'PSX.ISO').write_bytes(iso(rows[0][0].read_bytes()))
            else:
                for source,name in rows:
                    output=inside(folder,name);output.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,output)
        if target.exists():raise ValueError('assets appeared during staging; existing work is preserved')
        work.rename(target)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs',nargs='+',type=Path)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parent.parent)
    args=parser.parse_args()
    try:print(stage(args.project.resolve(),args.inputs))
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
