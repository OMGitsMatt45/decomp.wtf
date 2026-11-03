"""Offline, byte-guarded native VU programs from bounded local code profiles."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

MAX_IMAGES=512
MAX_ENTRIES=16384
MAX_ROUTINES=4096
MAX_PAIRS=131072


def read_profiles(directories):
    if not directories or len(directories)>32:raise ValueError('Use 1..32 local VU profile directories')
    images={};entries=set()
    for directory in map(Path,directories):
        listing=directory/'entries.txt'
        if not listing.is_file() or listing.stat().st_size>2*1024*1024:
            raise ValueError('Missing or oversized VU entries.txt')
        local={}
        for line in listing.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            fields=line.split()
            if len(fields)!=2 or not re.fullmatch('[0-9a-fA-F]{1,64}',fields[0]):
                raise ValueError('VU profile names must be bounded hexadecimal hashes')
            try:pc=int(fields[1],16)
            except ValueError:raise ValueError('Invalid VU entry PC') from None
            if pc<0 or pc>=16384 or pc&7:raise ValueError('VU entry must be aligned inside the code image')
            name=fields[0]
            if name not in local:
                path=directory/f'vu1-{name}.code'
                if not path.is_file() or path.stat().st_size!=16384:raise ValueError('VU1 code images must be exactly 16384 bytes')
                code=path.read_bytes();digest=hashlib.sha256(code).hexdigest()
                images.setdefault(digest,code);local[name]=digest
                if len(images)>MAX_IMAGES:raise ValueError('Too many VU code images')
            entries.add((local[name],pc))
            if len(entries)>MAX_ENTRIES:raise ValueError('Too many VU entry points')
    if not entries:raise ValueError('The VU profiles contain no entries')
    return images,entries


def empty(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'catalog.cpp').write_text('''// SPDX-License-Identifier: GPL-3.0-only
#include "ps2_vu1_program.h"
namespace ps2_vu_program {
const Entry *nativeEntries(size_t &count){count=0;return nullptr;}
}
''',encoding='utf-8')


def emit(runtime,directories,output,known_words,shards=32):
    if not 1<=shards<=64:raise ValueError('VU program shards must be 1..64')
    images,entries=read_profiles(directories);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    compiler=Path(runtime)/'thirdparty/PS2Recomp/tools/compile_vu_programs.py'
    spec=importlib.util.spec_from_file_location('_decomp_pinned_vu_program_compiler',compiler)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='.vu-program-inputs-',dir=output.parent) as temporary:
        normalized=Path(temporary)
        if not normalized.resolve().is_relative_to(output.parent.resolve()):raise ValueError('Unexpected VU staging path')
        for digest,code in images.items():(normalized/f'vu1-{digest}.code').write_bytes(code)
        (normalized/'entries.txt').write_text(''.join(f'{digest} {pc:x}\n' for digest,pc in sorted(entries)))
        decoded,starts=module.load_images([normalized],argparse.ArgumentParser())
        routines={}
        for digest,entry in starts:
            work=[entry];seen=set()
            while work:
                pc=work.pop()
                if pc in seen or pc>=module.PAIRS:continue
                seen.add(pc);routine=module.Routine(decoded[digest],pc)
                routines.setdefault(routine.key(),routine);work.extend(routine.calls)
                if len(routines)>MAX_ROUTINES:raise ValueError('Too many native VU routines')
        pairs=sum(len(r.footprint()) for r in routines.values())
        if pairs>MAX_PAIRS:raise ValueError('Native VU programs exceed their pair bound')
        for routine in routines.values():
            if any(routine.pairs[i].word not in known_words for i in routine.footprint()):
                raise ValueError('VU program contains a word absent from the input-bound native catalog')
        done=subprocess.run([sys.executable,str(compiler),'--output',str(output/'registry.inc'),
            '--shards',str(shards),'--max-routine-pairs','128',str(normalized)],capture_output=True,text=True,timeout=180)
        if done.returncode:raise ValueError('Pinned VU program generation failed: '+done.stderr[-2000:])
    (output/'catalog.cpp').write_text('''// SPDX-License-Identifier: GPL-3.0-only
#include "ps2_vu1_program.h"
#include "registry_extern.inc"
namespace ps2_vu_program {
namespace { const Entry entries[]={
#include "registry.inc"
}; }
const Entry *nativeEntries(size_t &count){count=sizeof(entries)/sizeof(entries[0]);return entries;}
}
''',encoding='utf-8')
    return dict(routines=len(routines),pairs=pairs,entries=len(entries),code_images=len(images),
        code_sha256=sorted(images),shards=shards,execution_model='guarded-static',runtime_compilation=False)


def qualification_inputs():
    """Original CC0 programs for wide/sliced execution and VU0 register jumps."""
    nop=0x2ff;lower_nop=0x8000033c
    loop=[(0x3dcccccd,nop|0x80000000),((8<<25)|(1<<16)|512,nop)]
    start=len(loop)
    for index in range(64):
        reg=3+index%4
        loop.append((lower_nop,(15<<21)|(reg<<11)|(reg<<6)|0x22))
    loop.extend([((9<<25)|(1<<16)|(1<<11)|1,nop),(lower_nop,nop)])
    branch=len(loop);loop.append(((0x29<<25)|(1<<11)|((start-branch-1)&0x7ff),nop))
    loop.extend([(lower_nop,nop),(lower_nop,nop|0x40000000),(lower_nop,nop)])
    jump=[((8<<25)|(1<<16)|7,nop),(lower_nop,nop),((0x24<<25)|(1<<11),nop),
        (lower_nop,nop),((8<<25)|(3<<16)|99,nop),(lower_nop,nop|0x40000000),
        (lower_nop,nop),((8<<25)|(3<<16)|7,nop),(lower_nop,nop),
        (lower_nop,nop|0x40000000),(lower_nop,nop)]
    # XGKICK starts six qwords before the wrap. The E-bit delay slot stores
    # into the first tag's payload while the packet is still in flight.
    terminal=[((8<<25)|(1<<16)|1017,nop),(lower_nop,nop),
        (0x800006fc|(1<<11),nop),(lower_nop,nop|0x40000000),
        ((1<<25)|(15<<21)|(1<<11)|1022,nop)]
    return {name:b''.join(struct.pack('<II',low,high) for low,high in pairs)
            for name,pairs in [('long-loop',loop),('register-jump',jump),('terminal-path1',terminal)]}


def fixtures(runtime,output,programs,known_words):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vu-fixture-profile-',dir=output.parent) as temporary:
        directory=Path(temporary);entries=[]
        for program in programs:
            code=program+bytes(16384-len(program));digest=hashlib.sha256(code).hexdigest()
            (directory/f'vu1-{digest}.code').write_bytes(code);entries.append(f'{digest} 0\n')
        (directory/'entries.txt').write_text(''.join(entries))
        return emit(runtime,[directory],output,known_words,shards=4)


def install(root,directories,shards):
    root=Path(root).resolve();manifest_path=root/'pc-project.json';manifest=json.loads(manifest_path.read_text())
    if manifest.get('backend',{}).get('id')!='ps2-ps2recomp-experimental':raise ValueError('Expected a native PS2 export')
    for name,digest in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or any(part in ('assets','saves','.git') for part in Path(name).parts):
            raise ValueError('Invalid export source path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Preserve changed export source: '+name)
    if 'DECOMP_PS2_NATIVE_VU_PROGRAMS' not in (root/'native/NativeExecution.cmake').read_text():
        raise ValueError('Re-export with native VU program support first')
    catalog=(root/'game/vu/catalog.cpp').read_text()
    words={int(w,16) for w in re.findall(r'\{0x([0-9a-f]{16})ull,decomp',catalog)}
    if not words:raise ValueError('The native VU input catalog is empty')
    target=root/'game/vu_programs';prefix='game/vu_programs/'
    if target.exists() and any(p.is_file() and prefix+p.name not in manifest['files'] for p in target.iterdir()):
        raise ValueError('Preserve untracked files in the native VU program folder')
    with tempfile.TemporaryDirectory(prefix='.vu-program-stage-',dir=root/'game') as temporary:
        stage=Path(temporary)
        if not stage.resolve().is_relative_to((root/'game').resolve()):raise ValueError('Unexpected program staging path')
        generated=stage/'output';record=emit(root/'runtime/ps2',directories,generated,words,shards)
        target.mkdir(exist_ok=True);names={p.name for p in generated.iterdir()}
        for old in list(target.iterdir()):
            if old.name not in names:
                if not old.is_file() or not old.resolve().is_relative_to(target.resolve()):raise ValueError('Unexpected old VU output')
                old.unlink();manifest['files'].pop(prefix+old.name,None)
        for path in generated.iterdir():
            if not path.is_file() or path.suffix not in ('.cpp','.inc'):raise ValueError('Unexpected generated VU file')
            destination=target/path.name;os.replace(path,destination)
            manifest['files'][prefix+path.name]=hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest['vu_generation']['whole_programs']=record
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=root,prefix='.vu-manifest-',suffix='.json',delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(manifest,indent=2)+'\n')
    try:os.replace(temporary,manifest_path)
    finally:temporary.unlink(missing_ok=True)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('profiles',nargs='+',type=Path)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--shards',type=int,default=32)
    args=parser.parse_args();print(json.dumps(install(args.project,args.profiles,args.shards),indent=2))


if __name__=='__main__':main()
