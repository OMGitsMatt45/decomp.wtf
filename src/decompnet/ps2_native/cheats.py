"""Input-bound data cheats and bounded, ahead-of-time EE function alternatives."""
import csv
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile

from ..pc import PCError
from . import modules, reports, runtime_patch
from .media import elf_info


def _offset(info, address, size):
    matches=[s['offset']+address-s['address'] for s in info['loads']
             if s['address']<=address and address+size<=s['address']+s['file_size']]
    if len(matches)!=1:raise PCError('PS2 cheat bytes need one exact file-backed mapping')
    return matches[0]


def prepare(spec, prepared):
    entries=spec.get('cheats',[])
    if not isinstance(entries,list) or len(entries)>4096:raise PCError('PS2 cheat entry bound exceeded')
    clean=[];groups={};seen=set();total=0
    for row in entries:
        ident=row.get('id','');name=row.get('name','');group=row.get('group','General')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) or ident in seen or not isinstance(name,str) or not 0<len(name)<=240 or not isinstance(group,str) or len(group)>100:
            raise PCError('invalid or duplicate PS2 cheat identity')
        seen.add(ident);data=[];code={};writes=[]
        for operation in row.get('writes',[]):
            a=operation.get('address');n=operation.get('size');v=operation.get('value')
            if type(a)is not int or type(n)is not int or type(v)is not int or n not in (1,2,4) or a<0 or a%n or a+n>0x02000000 or not 0<=v<1<<(8*n):
                raise PCError('PS2 cheat needs aligned, bounded EE RAM writes')
            writes.append(dict(address=a,size=n,value=v));total+=1
            if total>1_000_000:raise PCError('PS2 cheat operation bound exceeded')
            owners=[]
            for index,(original,mapping) in enumerate(prepared):
                overlap=any(r['address']<a+n and a<r['address']+r['size'] for r in mapping['code_ranges'])
                if not overlap:continue
                functions=[f for f in mapping['functions'] if f['address']<=a and a+n<=f['address']+f['size']]
                if not functions:raise PCError('PS2 code cheat is outside a mapped function')
                for function in functions:
                    key=(index,function['address']);owners.append(key)
                    entry=groups.setdefault(key,dict(module=index,function=function,members=[]))
                    code.setdefault(key,{})
                    for offset,byte in enumerate(v.to_bytes(n,'little')):code[key][a+offset]=byte
            if not owners:data.append(dict(address=a,size=n,value=v))
        clean.append(dict(id=ident,name=name,group=group,data=data,code=code,writes=writes))
    if len(groups)>128:raise PCError('PS2 cheat function-group bound exceeded')
    result=[]
    for index,(key,group) in enumerate(sorted(groups.items())):
        group['index']=index;group['key']=key
        members=[(i,e['code'][key]) for i,e in enumerate(clean) if key in e['code']]
        if len(members)>31:raise PCError('PS2 function has too many independent cheat selectors')
        combinations={0:{}}
        for bit,(cheat,patch) in enumerate(members):
            group['members'].append(dict(cheat=cheat,bit=1<<bit,patch=patch))
            additions={}
            for mask,previous in combinations.items():
                if all(a not in previous or previous[a]==v for a,v in patch.items()):
                    additions[mask|(1<<bit)]={**previous,**patch}
            combinations.update(additions)
            if len(combinations)>256:raise PCError('PS2 function cheat combinations exceed the compilation bound')
        group['alternatives']=[dict(mask=mask,bytes=patch) for mask,patch in sorted(combinations.items()) if mask]
        result.append(group)
    canonical=dict(entries=[{k:v for k,v in e.items() if k!='code'} for e in clean],
                   groups=[dict(module=g['module'],address=g['function']['address'],masks=[a['mask'] for a in g['alternatives']]) for g in result])
    return dict(entries=clean,groups=result,sha256=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest())


def header(root, policy):
    declarations=['#pragma once','#include "cheat_runtime.hpp"','namespace decomp_ps2_cheats {',
        'extern std::vector<Entry> entries;','uint32_t selection(size_t group);',
        'void toggle(size_t index);','void poll(uint8_t *ram);','}']
    lines=['#include "decomp_cheats.hpp"','namespace decomp_ps2_cheats {',
           f'std::atomic<uint32_t> active_masks[{max(1,len(policy["groups"]))}]{{}};',
           'std::vector<Entry> entries={']
    for index,entry in enumerate(policy['entries']):
        data=','.join('{'+f'{o["address"]}u,{o["value"]}u,{o["size"]}u'+'}' for o in entry['data'])
        selectors=[]
        for g in policy['groups']:
            selectors += ['{'+f'{g["index"]}u,{m["bit"]}u'+'}' for m in g['members'] if m['cheat']==index]
        writes=','.join('{'+f'{o["address"]}u,{o["value"]}u,{o["size"]}u'+'}' for o in entry['writes'])
        q=lambda x:json.dumps(x,ensure_ascii=True)
        lines.append('{'+','.join((q(entry['id']),q(entry['name']),q(entry['group']),'{'+data+'}','{'+','.join(selectors)+'}','{'+writes+'}'))+'},')
    lines += ['};',f'inline constexpr size_t group_count={len(policy["groups"])};',
              'uint32_t selection(size_t group){return active_masks[group].load(std::memory_order_acquire);}',
              'void toggle(size_t index){toggle_entry(entries,active_masks,group_count,index);}',
              'void poll(uint8_t *ram){poll_entries(entries,ram);}','}']
    (root/'native/decomp_cheats.hpp').write_text('\n'.join(declarations)+'\n',encoding='utf-8')
    (root/'native/cheats.cpp').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (root/'native/cheat_runtime.hpp').write_bytes(Path(__file__).with_name('cheat_runtime.hpp').read_bytes())
    (root/'native/settings.hpp').write_bytes(Path(__file__).with_name('settings.hpp').read_bytes())


def _resume_pcs(text):
    return {int(value,16) for value in re.findall(r'case 0x([0-9a-fA-F]+)u: goto label_',text)}


def _emit_choice(original,patch,start,size,label,destination,work,emitter,run):
    source=bytearray(modules.typed_elf(original,[dict(address=start,size=size)]))
    info=elf_info(source)
    for address,value in patch.items():source[_offset(info,address,1)]=value
    # Analysis-only entry; the owner's boot contract and RAM remain unchanged.
    struct.pack_into('<I',source,24,start)
    elf=work/'choice.elf';elf.write_bytes(source);csv_path=work/'choice.csv'
    with csv_path.open('w',newline='') as out:
        writer=csv.writer(out);writer.writerow(['Name','Start','End','Size']);writer.writerow([label,hex(start),hex(start+size),size])
    output=work/label;q=lambda p:json.dumps(p.as_posix());config=work/'choice.toml'
    config.write_text('[general]\ninput='+q(elf)+'\noutput='+q(output)+'\nghidra_output='+q(csv_path)+'\noutput_worker_threads=1\npatch_syscalls=false\npatch_cop0=true\npatch_cache=true\n')
    log=run([emitter,config],work,'Translate PS2 instruction choice '+label)
    counts=reports.generation_report(log,expected_functions=1);runtime_patch.install_vu_header(output)
    symbol=label+'_0x'+format(start,'x');text=(output/(symbol+'.cpp')).read_text(encoding='utf-8')
    destination.mkdir(parents=True,exist_ok=True)
    if '#include "decomp_vu0.hpp"' in text:(destination/'decomp_vu0.hpp').write_bytes((output/'decomp_vu0.hpp').read_bytes())
    if len(re.findall(r'void \w+\(uint8_t\* rdram, R5900Context\* ctx, PS2Runtime \*runtime\) \{',text))!=1:
        raise PCError('PS2 choice emitted an unexpected definition')
    text=text.replace('#include "ps2_recompiled_functions.h"','').replace('#include "ps2_recompiled_stubs.h"','')
    (destination/(label+'.cpp')).write_text(text,encoding='utf-8')
    return symbol,text,dict(entry=start,analysis_sha256=hashlib.sha256(source).hexdigest(),**counts)


def install(root, policy, prepared, records, emitter, run):
    """Each compiled alternative executes behind its original function's guard."""
    generated=[]
    if not policy['groups']:return generated
    destination=root/'game/alternatives';destination.mkdir()
    with tempfile.TemporaryDirectory(prefix='.ps2-choices-',dir=root.parent) as temporary:
        work=Path(temporary)
        for group in policy['groups']:
            original,mapping=prepared[group['module']];record=records[group['module']]
            function=group['function'];start=function['address'];size=function['size']
            folder=Path(record['path']);namespace=record['namespace']
            names={e['function'] for e in record['entries'] if e['address']==start}
            if len(names)!=1:raise PCError('PS2 cheat function has no unique original entry')
            public=names.pop();base=public+'_unchanged';declaration=f'void {public}(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime)'
            sources=[p for p in folder.glob(f'*_0x{start:x}.cpp') if declaration+' {' in p.read_text(encoding='utf-8')]
            if len(sources)!=1:raise PCError('PS2 cheat function definition differs')
            wrapper=['#include "ps2_runtime.h"',f'#include "{record["functions_header"]}"',f'#include "{namespace}.hpp"','#include "decomp_cheats.hpp"']
            wrapper.append(declaration.replace(public,base)+';')
            original_source=sources[0].read_text(encoding='utf-8')
            bodies={0:dict(symbol=base,text=original_source,patch={})}
            for alternative in group['alternatives']:
                label=f'choice_{group["index"]}_{alternative["mask"]}'
                symbol,text,statistics=_emit_choice(original,alternative['bytes'],start,size,label,destination,work,emitter,run)
                bodies[alternative['mask']]=dict(symbol=symbol,text=text,patch=alternative['bytes'])
                wrapper.append(f'void {symbol}(uint8_t*, R5900Context*, PS2Runtime*);')
                generated.append(dict(group=group['index'],mask=alternative['mask'],function=start,**statistics))
            # A patch can add calls/branches, creating resume PCs absent from
            # the original table. Every selection, including OFF, must accept
            # the union: a checkpoint may unwind just before the user toggles.
            resumes=set().union(*(_resume_pcs(body['text']) for body in bodies.values()))
            if len(resumes)>8192:raise PCError('PS2 cheat resume-entry bound exceeded')
            cases=[]
            for mask,body in bodies.items():
                lines=[f'case {mask}u:']
                for pc in sorted(resumes-_resume_pcs(body['text'])):
                    if not start<=pc<start+size:raise PCError('PS2 cheat resume exceeds its owner function')
                    label=f'choice_{group["index"]}_{mask}_resume_{pc:x}'
                    symbol,_,statistics=_emit_choice(original,body['patch'],pc,start+size-pc,label,
                        root/'native/cheat_resumes',work,emitter,run)
                    wrapper.append(f'void {symbol}(uint8_t*, R5900Context*, PS2Runtime*);')
                    lines.append(f'    if(ctx->pc=={pc}u){{{symbol}(rdram,ctx,runtime);return;}}')
                    generated.append(dict(group=group['index'],mask=mask,function=start,resume=True,**statistics))
                lines.append(f'    {body["symbol"]}(rdram,ctx,runtime); return;');cases+=lines
            known={entry['address'] for entry in record['entries']}
            additions=[dict(address=pc,function=public) for pc in sorted(resumes-known)]
            if additions:
                record['entries'].extend(additions);record['entries'].sort(key=lambda e:e['address'])
                record.setdefault('cheat_resume_entries',[]).extend(e['address'] for e in additions)
                (folder/'module.json').write_text(json.dumps({**record,'path':'.'},indent=2)+'\n',encoding='utf-8')
            wrapper += [declaration+' {',f'    {namespace}::check_range(rdram,{start}u,{size}u);',
                f'    const auto choice=decomp_ps2_cheats::selection({group["index"]}u);',
                '    if(choice) decomp_ps2_cheats::poll(rdram);',
                '    switch(choice) {',*cases,
                'default: throw std::runtime_error("uncompiled PS2 cheat selection");','    }','}']
            sources[0].write_text(original_source.replace(declaration+' {',declaration.replace(public,base)+' {',1),encoding='utf-8')
            (folder/f'choices_{group["index"]}.cpp').write_text('\n'.join(wrapper)+'\n',encoding='utf-8')
    return generated
