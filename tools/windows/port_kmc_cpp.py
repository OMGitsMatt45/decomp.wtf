#!/usr/bin/env python3
# GPL-2.0-or-later; converts the corresponding GPL sources distributed with the binaries.
import concurrent.futures, json, os, re, subprocess
from pathlib import Path

import argparse, shutil
parser=argparse.ArgumentParser(description="Port the configured KMC runtime translation units to GNU C++98")
parser.add_argument("build",type=Path)
parser.add_argument("--cc",default=os.environ.get("N64_REAL_CC","i686-w64-mingw32-gcc"))
parser.add_argument("--cxx",default=os.environ.get("WINDOWS_CXX","i686-w64-mingw32-g++"))
parser.add_argument("--jobs",type=int,default=4)
options=parser.parse_args()
ROOT=options.build.resolve()
BASE=ROOT/'baseline'
OUT=ROOT/'converted'; OUT.mkdir(exist_ok=True)
CC=shutil.which(options.cc) or options.cc
CXX=shutil.which(options.cxx) or options.cxx
ENV=os.environ.copy()
records=[]
for row in map(json.loads,(ROOT/'compiler-commands.jsonl').read_text().splitlines()):
    args=row['args']; cwd=Path(row['cwd'])
    src=next((a for a in reversed(args) if a.endswith('.c')),None)
    if '-c' not in args or not src or not (cwd/src).is_file() or Path(src).name.startswith('conftest'): continue
    key=str((cwd/src).resolve())+json.dumps(args)
    if any(r['key']==key for r in records): continue
    index=len(records); work=OUT/str(index);work.mkdir(exist_ok=True)
    row.update(key=key,source=str((cwd/src).resolve()),work=str(work),group='gcc' if str(cwd).startswith(str(BASE/'gcc')) else 'binutils')
    records.append(row)

def clean_args(args):
    out=[]; skip=False
    for a in args:
        if skip: skip=False;continue
        if a=='-o': skip=True;continue
        if a=='-c':continue
        out.append(a)
    return out

line_marker=re.compile(r'^#\s*(\d+)\s+"([^"]+)"(.*)$')
def collect(row):
    work=Path(row['work']); args=clean_args(row['args'])
    aux=work/'aux.txt'; pp=work/'preprocessed.txt'
    with (work/'collect.log').open('w') as log:
        subprocess.run([CC,*args,'-fsyntax-only','-aux-info',str(aux)],cwd=row['cwd'],env=ENV,check=True,stdout=log,stderr=log)
        with pp.open('w') as output:
            subprocess.run([CC,*args,'-E'],cwd=row['cwd'],env=ENV,check=True,stdout=output,stderr=log)
    current=''; headers=[]
    def own(name): return name.startswith(str(BASE)) or name==row['source'] or not name.startswith('/') and not name.startswith('<')
    for line in pp.read_text(errors='replace').splitlines(True):
        m=line_marker.match(line)
        if m:
            name=m[2]; flags=m[3].split()
            if '1' in flags and own(current) and not own(name) and not name.startswith('<'):
                if name not in headers: headers.append(name)
            current=name
    row['headers']=headers
    return row

if os.environ.get('N64_REUSE_COLLECT'):
    records=json.loads((ROOT/'conversion-records.json').read_text())
else:
    with concurrent.futures.ThreadPoolExecutor(max_workers=options.jobs) as pool:
        records=list(pool.map(collect,records))
(ROOT/'conversion-records.json').write_text(json.dumps(records,indent=2))

prototypes={'gcc':{},'binutils':{}}
local={}
aux_pattern=re.compile(r'/\* (.*?):(\d+):([ONI])([CF]) \*/ (.*?);')
proto_pattern=re.compile(r'\b([A-Za-z_]\w*)\s*\((.*)\)$')
for row in records:
    own_protos={}
    for line in (Path(row['work'])/'aux.txt').read_text().splitlines():
        m=aux_pattern.match(line)
        if not m:continue
        path,lineno,style,kind,proto=m.groups()
        if not (path.startswith(str(BASE)) or not path.startswith('/') or path==row['source']):continue
        p=proto_pattern.search(proto)
        if not p:continue
        name,args=p.groups()
        if '???' in args:continue
        if name not in own_protos or kind=='F':own_protos[name]=args
        if kind=='F' and not proto.startswith('static '):prototypes[row['group']][name]=args
    local[row['work']]=own_protos

keywords=set('class new delete this template operator typename public private protected friend virtual mutable namespace using explicit try catch throw const_cast static_cast reinterpret_cast dynamic_cast typeid bool true false wchar_t and or xor not bitand bitor compl and_eq or_eq xor_eq not_eq'.split())
tokens=re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*')
declaration=re.compile(r'(^[ \t]*(?:(?:extern|static|const|volatile|unsigned|signed|struct|enum)[ \t]+)*[A-Za-z_]\w*(?:[ \t]+|[ \t]*\*[ \t]*)+)([A-Za-z_]\w*)[ \t]*\([ \t]*\)[ \t]*;',re.M)

def type_intervals(text):
    lex=re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
    stack=[];result=[]
    for m in lex.finditer(text):
        if m[0]=='{':
            p=re.search(r'\b(struct|union|enum)(?:\s+(\w+))?\s*$',text[max(0,m.start()-150):m.start()])
            start=max(0,m.start()-150)+p.start() if p else m.start()
            stack.append((start,m.start(),p[1] if p else '',p[2] if p else None))
        elif m[0]=='}' and stack:
            start,opening,kind,name=stack.pop()
            if kind:result.append((start,opening,m.end(),kind,name))
    return result

def decl_start(text,at):
    p=re.search(r'\b(?:(?:typedef|static|extern|const|volatile)\s+)+$',text[:at])
    return p.start() if p else at

def port_types(text):
    intervals=type_intervals(text)
    enums=[r for r in intervals if r[3]=='enum'];edits=[];aliases={}
    for index,(start,opening,end,kind,name) in enumerate(enums):
        key=name or 'anonymous_'+str(index)
        alias='n64_enum_'+key; actual='n64_cpp_enum_'+key
        if name:aliases[name]=alias
        parents=[r for r in intervals if r[3] in ('struct','union') and r[0]<start and end<r[2]]
        before=decl_start(text,min(parents)[0] if parents else start)
        definition='enum '+actual+text[opening:end]+';\ntypedef __underlying_type(enum '+actual+') '+alias+';\n'
        edits.append((before,before,definition))
        tail=text[end:]; semicolon=re.match(r'\s*;',tail)
        if semicolon:edits.append((start,end+semicolon.end(),''))
        else:edits.append((start,end,alias))
    for start,end,replacement in sorted(edits,reverse=True):text=text[:start]+replacement+text[end:]
    text=re.sub(r'\benum\s+(\w+)',lambda m:aliases.get(m[1],m[0]),text)
    # C tags have their own namespace; C++ classes share the typedef namespace.
    tags={name:kind for _,_,_,kind,name in type_intervals(text) if kind in ('struct','union') and name}
    text=re.sub(r'\b(struct|union)\s+(\w+)',lambda m:m[1]+' n64_tag_'+m[2] if m[2] in tags else m[0],text)
    # A tagged type declared inside a C aggregate belongs to the enclosing C
    # scope. Hoist its C++ definition to that scope rather than making a member.
    for iteration in range(100):
        intervals=type_intervals(text);nested=[]
        for r in intervals:
            if r[3] not in ('struct','union') or not r[4]:continue
            parents=[p for p in intervals if p[3] in ('struct','union') and p[0]<r[0] and r[2]<p[2]]
            if parents:nested.append((r,min(parents)))
        if not nested:break
        r,parent=min(nested,key=lambda pair:pair[0][2]-pair[0][0])
        definition=text[r[0]:r[2]]+';\n';before=decl_start(text,parent[0])
        text=text[:r[0]]+r[3]+' '+r[4]+text[r[2]:]
        text=text[:before]+definition+text[before:]
    return ''.join(kind+' n64_tag_'+name+';\n' for name,kind in sorted(tags.items()))+text

def generate(row):
    work=Path(row['work']);protos=prototypes[row['group']]|local[row['work']]
    current=''; lines=[];system_files=set()
    for line in (work/'preprocessed.txt').read_text().splitlines():
        m=line_marker.match(line)
        if m and '1' in m[3].split() and '3' in m[3].split():system_files.add(m[2])
    for line in (work/'preprocessed.txt').read_text().splitlines(True):
        m=line_marker.match(line)
        if m:
            current=m[2]
        elif current not in system_files and not current.startswith('<'):lines.append(line)
    text=''.join(lines)
    # Use GCC's own typed definition inventory rather than guessing K&R types.
    implicit=[]
    names=set(protos)
    for line in (work/'aux.txt').read_text().splitlines():
        m=aux_pattern.match(line)
        if not m:continue
        path,lineno,style,kind,proto=m.groups()
        if path in system_files:continue
        p=proto_pattern.search(proto)
        if not p:continue
        name,args=p.groups();names.add(name)
        if style=='I':implicit.append(proto[:p.start(1)]+name+'(...) asm("_'+name+'");\n')
        if style=='O' and kind=='F':
            old=re.search(r'; /\* \(([^)]*)\)',line)
            if old:
                old_args=r'\s*,\s*'.join(map(re.escape,old[1].split(', ')))
                pattern=re.compile(r'\b'+re.escape(name)+r'\s*\(\s*'+old_args+r'\s*\)\s*(?!;)([^{}]*?)\{')
                def definition(match):
                    decls=match[1].strip()
                    if old[1]:
                        if decls and (not decls[0].isalpha() or not decls.endswith(';')):return match[0]
                        if decls and decls.split()[0] in ('if','return','while','for','else','switch','case','do','goto'):return match[0]
                    elif decls:return match[0]
                    previous=text[:match.start()].rstrip().rsplit('\n',1)[-1].strip()
                    implicit_return=(not previous or previous.endswith(('}', ';')) or previous in ('static','extern','inline'))
                    return ('int ' if implicit_return and re.match(r'(?:extern |static )?int\b',proto) else '')+name+'('+args+')\n{'
                text=pattern.sub(definition,text)
    # C's unprototyped declarations permit promoted arguments. Preserve that
    # ABI with C++ overload declarations carrying explicit C assembler labels.
    text=text.replace('/* ??? */','...')
    text=port_types(text)
    text=re.sub(r'\b(register|static|extern)\s+(\w+)\s*(?=[=;,])',r'\1 int \2 ',text)
    while re.search(r'\b(const|volatile)\s+\1\b',text):text=re.sub(r'\b(const|volatile)\s+\1\b',r'\1',text)
    text=declaration.sub(lambda m:m[0] if m[1].strip() in ('return','goto') else m[1]+m[2]+'(...);',text)
    pointer=re.compile(r'(\b[A-Za-z_]\w*\s*\**\s*\(\s*\*+\s*(?:\w+\s*(?:\[[^\]]*\])*)?\s*\))\s*\(\s*\)')
    text=pointer.sub(lambda m:m[0] if m[1].startswith('return') else m[1]+'(...)',text)
    text=re.sub(r'(\btypedef\s+[\w\s*]+\s+\w+)\s*\(\s*\)\s*;',r'\1(...);',text)
    # Also handle comma-separated global declarators and qualified callback arrays.
    text=re.sub(r'(\(\s*\*+\s*(?:const\s+|volatile\s+)*\w+(?:\s*\[[^\]]*\])+\s*\))\s*\(\s*\)',r'\1(...)',text)
    conditional=re.compile(r'\b(\w+)\s*\(\*(\w+)\)\(\.\.\.\)\s*=\s*\(([^?;]+)\?\s*(\w+)\s*:\s*(\w+)\s*\);')
    text=conditional.sub(lambda m:m[1]+' (*'+m[2]+')(...) = ('+m[3]+' ? ('+m[1]+' (*)(...))'+m[4]+' : ('+m[1]+' (*)(...))'+m[5]+');',text)
    mask=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m[0]),text)
    changes=[];depth=0;cursor=0
    for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\((\s*|\.\.\.)\)\s*(?=[;,])',mask):
        depth+=mask[cursor:m.start()].count('{')-mask[cursor:m.start()].count('}');cursor=m.start()
        if depth:continue
        start=text.index('(',m.start());end=text.index(')',start)+1
        arguments='void' if protos.get(m[1]) in ('void','') or m[1]=='abort' else '...'
        label=' asm("_'+m[1]+'")' if m[1] in names else ''
        changes.append((start,end,'('+arguments+')'+label))
    for start,end,replacement in reversed(changes):text=text[:start]+replacement+text[end:]
    # Annotate both declarations and definitions before any use. This does not
    # link a C implementation: every body is compiled by the C++ compiler.
    names.update(re.findall(r'\bextern\s+errorfn\s+(\w+)\s*;',text))
    names=sorted(names,key=len,reverse=True)
    text=re.sub(r'(^[ \t]*extern[ \t]+\w+[ \t]+)('+'|'.join(map(re.escape,names))+r')\s*;',
                lambda m:m[1]+m[2]+' asm("_'+m[2]+'");',text,flags=re.M)
    pattern=re.compile(r'(^[ \t]*(?:(?:extern|static|inline|const|volatile|unsigned|signed|struct|enum)[ \t]+)*[A-Za-z_]\w*(?:(?:[ \t]+[A-Za-z_]\w*)|[ \t]*\*)*[ \t\n]*)\b('+'|'.join(map(re.escape,names))+r')\s*\(',re.M)
    inserts=[]
    for m in pattern.finditer(text):
        if m[1].strip().split()[0] in ('return','goto','else','if','while','for','switch','case','do'):continue
        end=m.end();depth=1
        while depth and end<len(text):
            depth+=(text[end]=='(')-(text[end]==')');end+=1
        following=text[end:].lstrip()
        label=' asm("_'+m[2]+'")'
        if following.startswith(';') or following.startswith('__attribute__'):inserts.append((end,label))
        elif following.startswith('{'):
            inserts.append((m.start(),text[m.start():end]+label+';\n'))
    for at,value in sorted(inserts,reverse=True):text=text[:at]+value+text[at:]
    text=text.replace('rtx (*const insn_gen_function[])(...) =', 'extern rtx (*const insn_gen_function[])(...) =')
    text=text.replace('libiberty_voidfn xexit;', 'libiberty_voidfn xexit asm("_xexit");')
    # C file-scope const objects have external linkage; preserve it in C++.
    mask=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m[0]),text)
    edits=[]; cursor=0; depth=0
    for m in re.finditer(r'^const\s+[^;{}\n]+=',mask,re.M):
        depth+=mask[cursor:m.start()].count('{')-mask[cursor:m.start()].count('}');cursor=m.start()
        if depth==0:edits.append(m.start())
    for at in reversed(edits):text=text[:at]+'extern '+text[at:]
    # The old C++ frontend intentionally uses unprototyped diagnostic calls,
    # and callback declarations that coexist with typed K&R definitions.
    # Preserve their original C calling ABI without changing argument lists.
    if '/gcc/cp/' in row['source']:
        # These legacy C helpers fall off a non-void body. Every caller discards
        # their return value. GCC 14's C++ compiler traps on that path even at
        # -O0, so make the discarded result explicit without changing effects.
        for name in ('note_level_for_for','pushdecl_nonclass_level','do_toplevel_using_decl',
                     'start_eh_unwinder','end_eh_unwinder'):
            definition=re.search(r'\b'+name+r'\([^;{}]*\)\s*\{',text)
            if not definition:continue
            opening=definition.end()-1; level=1; end=opening+1
            body_mask=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m[0]),text)
            while level:
                level+=(body_mask[end]=='{')-(body_mask[end]=='}');end+=1
            body=re.sub(r'\breturn\s*;', 'return 0;',text[opening+1:end-1])
            text=text[:opening+1]+body+'\n  return 0;\n'+text[end-1:]
        callbacks = {
            'rank_for_overload': '(int (*)(const void*, const void*))(int (*)(struct n64_tag_candidate*, struct n64_tag_candidate*))',
            'dfs_init_vbase_pointers': '(void (*)(...))(void (*)(tree))',
            'dfs_compress_decls': '(void (*)(...))(void (*)(tree))',
        }
        for name, cast in callbacks.items():
            text=tokens.sub(lambda m:cast+name if m[0]==name and not re.match(r'\s*\(',text[m.end():]) else m[0],text)
        legacy = {
            'user_harshness': 'int (*)(tree, tree, tree)',
            'ack': 'void (*)(char*, int, int)',
            'dump_readonly_or_volatile': 'void (*)(tree, n64_enum_pad)',
            'dump_expr_list': 'void (*)(tree)',
        }
        mask=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m[0]),text)
        edits=[]; depth=0; cursor=0
        for m in re.finditer(r'\b('+'|'.join(legacy)+r')\s*(?=\()',mask):
            depth+=mask[cursor:m.start()].count('{')-mask[cursor:m.start()].count('}');cursor=m.start()
            if depth:
                result='int' if m[1]=='user_harshness' else 'void'
                edits.append((m.start(),m.end(),'(('+result+' (*)(...))('+legacy[m[1]]+')'+m[1]+')'))
        for start,end,value in reversed(edits):text=text[:start]+value+text[end:]
    text=tokens.sub(lambda m:'' if m[0] in ('inline','__inline__','__inline') else 'cxx_'+m[0] if m[0] in keywords or m[0]=='getch' else 'bool' if m[0]=='_Bool' else m[0],text)
    source=work/'implementation.cpp'
    headers=['#include <'+h.rsplit('/include/',1)[-1]+'>\n' for h in row['headers']]
    notices=[]
    for name in sorted({row['source']} | {m[2] for line in (work/'preprocessed.txt').read_text().splitlines() if (m:=line_marker.match(line)) and m[2].startswith(str(BASE))}):
        original=Path(name)
        if not original.is_file():continue
        for comment in re.findall(r'/\*.*?\*/',original.read_text(errors='replace'),re.S):
            if 'Copyright' in comment or 'copyright' in comment:
                notices.append('// From '+str(original.relative_to(BASE))+'\n'+comment+'\n')
    forward = 'int cxx_getch(void) asm("_getch");\n' if row['source'].endswith('/cp/lex.c') else ''
    source.write_text('// GNU C++98 host port; original algorithms retained. GPL-2.0-or-later.\n'+''.join(notices)+'#include <stdlib.h>\n#include <string.h>\n#include <stdio.h>\n'+''.join(headers)+'#include <getopt.h>\nextern "C" void bcopy(const void*,void*,size_t);\nextern "C" int fork(void);\n'+forward+''.join(implicit)+text+'\n')
    args=clean_args(row['args']); args=[str(source) if str((Path(row['cwd'])/a).resolve())==row['source'] else a for a in args]
    args=['-std=gnu++98' if a.startswith('-std=') else a for a in args]
    args=[a for a in args if not a.startswith('-I')]
    with (work/'cpp-errors.log').open('w') as log:
        result=subprocess.run([CXX,*args,'-fpermissive','-fno-exceptions','-fno-rtti','-c','-o',str(work/'implementation.o'),'-fmax-errors=15'],cwd=row['cwd'],env=ENV,stdout=log,stderr=log)
    return row,result.returncode

with concurrent.futures.ThreadPoolExecutor(max_workers=options.jobs) as pool:
    results=list(pool.map(generate,records))
failed=[r for r,code in results if code]
print('translation units:',len(results),'passed:',len(results)-len(failed),'failed:',len(failed))
for r in failed[:8]:
    log=Path(r['work'])/'cpp-errors.log'
    errors=[line for line in log.read_text().splitlines() if 'error:' in line]
    print(r['work'],r['source'],*errors[:3],sep='\n')

if failed:raise SystemExit(1)
