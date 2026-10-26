"""Bounded read-only RomFS module extraction, including seekable archive sources."""
from __future__ import annotations

import hashlib
import struct

from ..pc import PCError
from .media import _range

INVALID = 0xffffffff
MAX_METADATA = 32*1024*1024
MAX_MODULE = 64*1024*1024
MAX_MODULES = 128*1024*1024
MAX_ENTRIES = 100000


def validate_module(raw, *, static=False):
    """Bound the pinned emitter's CRO metadata before it allocates any tables."""
    if len(raw)<0x138 or raw[0x80:0x84]!=b'CRO0':
        raise PCError('3DS module has no bounded CRO0 header')
    word=lambda at:struct.unpack_from('<I',raw,at)[0]
    strings={}
    def string(at,limit=4096):
        if at not in strings:
            _range(at,1,len(raw),'CRO string')
            end=raw.find(b'\0',at,min(len(raw),at+limit+1))
            if end<0:
                raise PCError('3DS CRO string is unterminated or exceeds its bound')
            strings[at]=raw[at:end]
        if len(strings[at])>limit:
            raise PCError('3DS CRO string exceeds its bound')
        return strings[at]
    name=string(word(0xc0),255)
    if not name or any(b<33 or b>126 or b in (34,92) for b in name):
        raise PCError('3DS module name cannot be represented safely in generated C')
    tables=[];total=0
    for at,stride in ((0xc8,12),(0xd0,8),(0xd8,4),(0xf0,20),(0xf8,12),(0x128,12)):
        offset,count=word(at),word(at+4)
        total+=count
        if total>MAX_ENTRIES or at==0xc8 and count>16:
            raise PCError('3DS CRO metadata has too many symbols or segments')
        _range(offset,count*stride,len(raw),'CRO metadata table')
        tables.append((at,offset,count,stride))
    for at,offset,count,stride in tables:
        for index in range(count):
            row=offset+index*stride
            if at==0xc8:
                address,size,kind=struct.unpack_from('<III',raw,row)
                if kind>3 or address+size>0x10000000:
                    raise PCError('3DS CRO segment kind/address is invalid')
                if not static and kind!=3:
                    _range(address,size,len(raw),'CRO initialized segment')
            elif at==0xd0:
                string(word(row))
            elif at==0xf0:
                string(word(row))
                symbols,n=word(row+12),word(row+16)
                total+=n
                if total>MAX_ENTRIES:
                    raise PCError('3DS CRO imports exceed their metadata bound')
                _range(symbols,n*8,len(raw),'CRO anonymous imports')
    return name.decode('ascii')


def modules(source, inspection):
    """Return validated CRO/CRS payloads without unpacking all game assets.

    File names remain metadata. Callers store payloads under generated numeric
    names, never paths taken from the original image. Whole-input SHA identity
    and per-module hashes bind the export; IVFC hash-tree verification is not
    claimed by this directory walker.
    """
    section = next((s for s in inspection['sections'] if s['name']=='romfs'),None)
    if section is None:
        return []
    with source.open('rb') as stream:
        def read(at, size, end, what):
            _range(at,size,end,what)
            stream.seek(at)
            raw=stream.read(size)
            if len(raw)!=size:
                raise PCError('3DS RomFS input is truncated: '+what)
            return raw
        start,end=section['offset'],section['offset']+section['size']
        header=read(start,0x60,end,'IVFC header')
        if header[:4]!=b'IVFC' or struct.unpack_from('<I',header,4)[0]!=0x10000:
            raise PCError('3DS RomFS requires an IVFC version 0x10000 header')
        master=struct.unpack_from('<I',header,8)[0]
        level_size=struct.unpack_from('<Q',header,0x44)[0]
        shift=struct.unpack_from('<I',header,0x4c)[0]
        if shift>20 or master>MAX_METADATA:
            raise PCError('3DS RomFS hash/header allocation exceeds its bound')
        block=1<<shift
        base=start+((0x60+master+block-1)//block)*block
        _range(base,level_size,end,'RomFS level 3')
        level_end=base+level_size
        fields=struct.unpack('<10I',read(base,0x28,level_end,'level 3 header'))
        if fields[0]!=0x28:
            raise PCError('3DS RomFS level 3 header size is invalid')
        regions=[]
        for index in range(1,9,2):
            offset,size=fields[index:index+2]
            _range(offset,size,level_size,'RomFS metadata')
            if size and (offset<0x28 or any(offset<b+n and b<offset+size for b,n in regions)):
                raise PCError('3DS RomFS metadata overlaps headers or another table')
            regions.append((offset,size))
        if sum(n for _,n in regions)>MAX_METADATA:
            raise PCError('3DS RomFS metadata exceeds its allocation bound')
        data_offset=fields[9]
        if data_offset<max([0x28,*[offset+size for offset,size in regions]]) or data_offset>level_size:
            raise PCError('3DS RomFS file data overlaps its metadata')
        # Read metadata in physical order so streamed sources need fewer restarts.
        tables={}
        for name,index in sorted((('dirs',3),('files',7)),key=lambda row:fields[row[1]]):
            tables[name]=read(base+fields[index],fields[index+1],level_end,'RomFS '+name)

        def entry(table,at,directory):
            fixed=0x18 if directory else 0x20
            if at%4:
                raise PCError('3DS RomFS entry is not aligned')
            _range(at,fixed,len(table),'RomFS directory/file entry')
            size=struct.unpack_from('<I',table,at+fixed-4)[0]
            if size%2 or size>1024:
                raise PCError('3DS RomFS UTF-16 name length is invalid')
            _range(at+fixed,size,len(table),'RomFS name')
            try:
                name=table[at+fixed:at+fixed+size].decode('utf-16-le')
            except UnicodeDecodeError as error:
                raise PCError('3DS RomFS name is not valid UTF-16') from error
            if name in ('.','..') or any(c in name for c in ('/','\\','\0')):
                raise PCError('3DS RomFS name contains a path component')
            return name

        dirs,files=tables['dirs'],tables['files']
        pending=[(0,'',0)]
        seen_dirs={0};seen_files=set();selected=[];paths=set()
        total=0
        while pending:
            at,path,depth=pending.pop()
            if depth>128 or len(path)>4096:
                raise PCError('3DS RomFS directory depth/path exceeds its bound')
            entry(dirs,at,True)
            parent,sibling,child,file=struct.unpack_from('<4I',dirs,at)
            if at==0 and parent not in (0,INVALID):
                raise PCError('3DS RomFS root has an invalid parent')
            names=set()
            while child!=INVALID:
                if child in seen_dirs:
                    raise PCError('3DS RomFS directory links cycle or repeat an entry')
                seen_dirs.add(child)
                name=entry(dirs,child,True)
                if struct.unpack_from('<I',dirs,child)[0]!=at:
                    raise PCError('3DS RomFS child directory parent differs')
                if name.casefold() in names:
                    raise PCError('3DS RomFS directory repeats a child name')
                names.add(name.casefold())
                pending.append((child,'/'.join(p for p in (path,name) if p),depth+1))
                child=struct.unpack_from('<I',dirs,child+4)[0]
                if len(seen_dirs)+len(seen_files)>MAX_ENTRIES:
                    raise PCError('3DS RomFS has too many entries')
            while file!=INVALID:
                if file in seen_files:
                    raise PCError('3DS RomFS file links cycle or repeat an entry')
                seen_files.add(file)
                name=entry(files,file,False)
                parent,next_file,offset,size=struct.unpack_from('<IIQQ',files,file)
                if parent!=at or not name or name.casefold() in names:
                    raise PCError('3DS RomFS file parent/name is invalid or repeated')
                names.add(name.casefold())
                absolute=base+data_offset+offset
                _range(absolute,size,level_end,'RomFS file payload')
                logical='/'.join(p for p in (path,name) if p)
                if logical.casefold() in paths:
                    raise PCError('3DS RomFS flattened paths repeat a name')
                paths.add(logical.casefold())
                if name.lower().endswith(('.cro','.crs')):
                    total+=size
                    if not 0x138<=size<=MAX_MODULE or total>MAX_MODULES:
                        raise PCError('3DS CRO/CRS payload exceeds its size/allocation bound')
                    selected.append((absolute,size,logical))
                file=next_file
                if len(seen_dirs)+len(seen_files)>MAX_ENTRIES:
                    raise PCError('3DS RomFS has too many entries')
        # Read-only file extents may alias (deduplicated assets). Their bounds
        # and identities matter; overlapping payloads do not authorize writes.
        result=[]
        for absolute,size,path in sorted(selected):
            raw=read(absolute,size,level_end,'CRO/CRS payload')
            validate_module(raw,static=path.lower().endswith('.crs'))
            result.append(dict(path=path,size=size,sha256=hashlib.sha256(raw).hexdigest(),data=raw))
        return result
