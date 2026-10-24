"""Input-bound EE code maps; title addresses never enter the shared runtime."""
import hashlib
import gzip
import io
from importlib import resources
import json
from pathlib import Path, PurePosixPath
import re

from elftools.elf.elffile import ELFFile

from ..pc import PCError
from .media import MAX_PROGRAM, elf_info

SCHEMA = 'decomp.wtf.ps2-profile/v1'


def number(value):
    if isinstance(value,str):
        try:value=int(value,0)
        except ValueError as error:raise PCError('invalid PS2 profile integer') from error
    if type(value) is not int or value < 0 or value > 0xffffffff:
        raise PCError('invalid PS2 profile integer')
    return value


def module(original, row=None):
    info=elf_info(original)
    if row is None:
        functions=[]
        elf=ELFFile(io.BytesIO(original))
        for section in elf.iter_sections():
            if section['sh_type'] not in ('SHT_SYMTAB','SHT_DYNSYM'):continue
            for symbol in section.iter_symbols():
                if symbol['st_info']['type']=='STT_FUNC' and symbol['st_size'] and isinstance(symbol['st_shndx'],int):
                    functions.append(dict(name=f'function_{symbol["st_value"]:08x}',address=symbol['st_value'],size=symbol['st_size']))
        functions=list({f['address']:f for f in functions}.values())
        if not functions:
            from .recovery import closed_module
            row=closed_module(original)
        else:row=dict(sha256=info['sha256'],functions=functions,native_services=[],code_ranges=[dict(address=s['address'],size=s['size']) for s in info['executable_sections']])
    if row.get('sha256')!=hashlib.sha256(original).hexdigest():
        raise PCError('PS2 profile module SHA-256 differs from the owner input')
    functions=row.get('functions',[])
    if not isinstance(functions,list) or not 0<len(functions)<=100000:
        raise PCError('PS2 profile needs a bounded function list')
    ranges=[]
    executable=[*info['executable_sections'],*[dict(address=s['address'],size=s['file_size'])
        for s in info['loads'] if s['flags']&1 and s['file_size']]]
    for item in row.get('code_ranges',[]):
        a,n=number(item['address']),number(item['size'])
        if not n or a&3 or n&3 or not any(s['address']<=a and a+n<=s['address']+s['size'] for s in executable):
            raise PCError('PS2 profile code range is outside declared executable bytes')
        ranges.append(dict(address=a,size=n))
    ranges.sort(key=lambda x:x['address'])
    if not ranges or any(a['address']+a['size']>b['address'] for a,b in zip(ranges,ranges[1:])):
        raise PCError('PS2 profile needs non-overlapping typed code ranges')
    clean=[]
    for item in functions:
        name=item['name'];a,n=number(item['address']),number(item['size'])
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z_]\w{0,199}',name,re.ASCII):
            raise PCError('PS2 profile function name is not an identifier')
        if not n or a&3 or n&3 or not any(s['address']<=a and a+n<=s['address']+s['size'] for s in ranges):
            raise PCError('PS2 profile function crosses a typed code/data boundary')
        clean.append(dict(name=name,address=a,size=n))
    clean.sort(key=lambda x:x['address'])
    # Alternate entry points may share instructions/epilogues. Each entry must
    # still be unique and wholly contained in an explicitly typed code range.
    if len({f['address'] for f in clean})!=len(clean):
        raise PCError('PS2 profile repeats a function entry')
    services=row.get('native_services',[])
    if not isinstance(services,list):raise PCError('PS2 native services must be explicit')
    bindings=[]
    for item in services:
        a=number(item['address']);name=item['name']
        if not re.fullmatch(r'[A-Za-z_]\w{0,199}',name,re.ASCII) or a not in {f['address'] for f in clean}:
            raise PCError('PS2 native service must name a mapped SDK function')
        bindings.append(dict(address=a,name=name))
    if len({s['address'] for s in bindings})!=len(bindings):raise PCError('duplicate PS2 native service binding')
    result=dict(sha256=info['sha256'],functions=clean,code_ranges=ranges,native_services=bindings)
    if row.get('recovery'):result['recovery']=row['recovery']
    return result


def load(path,input_identity):
    raw=Path(path).read_bytes()
    if len(raw)>32*1024*1024:raise PCError('PS2 profile exceeds its size bound')
    return document(json.loads(raw),input_identity)


def known(input_identity):
    """Optional data profiles are selected only by the complete original hash."""
    root=resources.files(__package__).joinpath('profiles')
    index=json.loads(root.joinpath('index.json').read_text(encoding='utf-8'))
    item=index.get(input_identity)
    if item is None:return None
    name=item['file']
    if not re.fullmatch('[a-z0-9-]+[.]json[.]gz',name):raise PCError('invalid bundled PS2 profile path')
    compressed=root.joinpath(name).read_bytes()
    if hashlib.sha256(compressed).hexdigest()!=item['sha256']:raise PCError('bundled PS2 profile checksum differs')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:raw=stream.read(32*1024*1024+1)
    if len(raw)>32*1024*1024:raise PCError('bundled PS2 profile exceeds its size bound')
    return document(json.loads(raw),input_identity)


def document(data,input_identity):
    if data.get('schema')!=SCHEMA or data.get('input_sha256')!=input_identity:
        raise PCError('PS2 profile schema or original input SHA-256 differs')
    rows=data.get('modules',[])
    if not isinstance(rows,list) or not 0<len(rows)<=1024:raise PCError('PS2 profile needs a bounded module list')
    for row in rows:
        name=row.get('path','');parts=PurePosixPath(name)
        if not name or parts.is_absolute() or any(p in ('.','..') for p in parts.parts) or '\\' in name or ':' in name:
            raise PCError('PS2 profile module path must stay inside the input disc')
    if len({r['path'] for r in rows})!=len(rows):raise PCError('PS2 profile repeats a module')
    return data
