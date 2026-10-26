"""Original module fixtures and malformed read-only RomFS layouts."""
import hashlib
from io import BytesIO
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from decompnet.pc import PCError
from decompnet.ctr_native import media,romfs
from tools.ctr_fixture import fixture,cro,with_romfs


def source(raw):
    return SimpleNamespace(open=lambda mode:BytesIO(raw),stat=lambda:SimpleNamespace(st_size=len(raw)))


def test_romfs_selects_only_code_modules_with_independent_identity_and_streams():
    module=cro()
    raw=with_romfs(fixture(),[('greeting.txt',b'Original asset'),('Original.cro',module)])
    data=source(raw);inspection=media.load_source(data)
    result=romfs.modules(data,inspection)
    assert result==[dict(path='Original.cro',size=len(module),data=module,sha256=hashlib.sha256(module).hexdigest())]
    assert romfs.modules(source(fixture()),media.load_source(source(fixture())))==[]


@pytest.mark.parametrize('directory',['','モジュール'])
def test_nameless_wrapper_and_utf16_directory_paths(directory):
    data=source(with_romfs(fixture(),[('Original.cro',cro())],directory=directory))
    rows=romfs.modules(data,media.load_source(data))
    assert rows[0]['path']==('/'.join([directory,'Original.cro']) if directory else 'Original.cro')


def test_read_only_aliases_keep_their_own_names_and_the_same_bytes():
    raw=bytearray(with_romfs(fixture(),[('Original.cro',cro()),('Alias.cro',cro())]))
    inspection=media.load_source(source(raw))
    base=next(s['offset'] for s in inspection['sections'] if s['name']=='romfs')+0x1000
    table=base+struct.unpack_from('<I',raw,base+0x1c)[0]
    sibling=struct.unpack_from('<I',raw,table+4)[0]
    struct.pack_into('<Q',raw,table+sibling+8,0)
    rows=romfs.modules(source(raw),inspection)
    assert len(rows)==2 and rows[0]['path']!=rows[1]['path']
    assert rows[0]['data']==rows[1]['data'] and rows[0]['sha256']==rows[1]['sha256']


@pytest.mark.parametrize('change',['segments','symbols','unterminated','module-name','code-range','imports'])
def test_cro_metadata_is_bounded_before_the_emitter_allocates_tables(change):
    raw=bytearray(cro())
    if change=='segments':struct.pack_into('<I',raw,0xcc,0xffffffff)
    elif change=='symbols':struct.pack_into('<I',raw,0xd4,0xffffffff)
    elif change=='unterminated':raw[0x180:]=b'X'*(len(raw)-0x180)
    elif change=='module-name':raw[0x180]=ord('"')
    elif change=='code-range':struct.pack_into('<I',raw,0x13c,0xffffffff)
    elif change=='imports':struct.pack_into('<II',raw,0xf0,0x138,1);struct.pack_into('<II',raw,0x144,0x100,0xffffffff)
    with pytest.raises(PCError):romfs.validate_module(raw)


@pytest.mark.parametrize('change',['ivfc','block','metadata-overlap','name','payload','cycle','parent','header'])
def test_malformed_romfs_fails_without_following_paths_or_unbounded_links(change):
    raw=bytearray(with_romfs(fixture(),[('Original.cro',cro())]))
    inspection=media.load_source(source(raw))
    base=next(s['offset'] for s in inspection['sections'] if s['name']=='romfs')
    level=base+0x1000
    file_meta=struct.unpack_from('<I',raw,level+0x1c)[0]
    if change=='ivfc':raw[base]=0
    elif change=='block':struct.pack_into('<I',raw,base+0x4c,31)
    elif change=='metadata-overlap':struct.pack_into('<I',raw,level+0x1c,0x2c)
    elif change=='name':raw[level+file_meta+0x20:level+file_meta+0x26]='../'.encode('utf-16-le')
    elif change=='payload':struct.pack_into('<Q',raw,level+file_meta+8,0xffffffffffffffff)
    elif change=='cycle':struct.pack_into('<I',raw,level+file_meta+4,0)
    elif change=='parent':struct.pack_into('<I',raw,level+file_meta,4)
    elif change=='header':struct.pack_into('<I',raw,level,0)
    with pytest.raises(PCError):romfs.modules(source(raw),inspection)
