"""Static modules with independent byte identities, including shared disc addresses."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

EXPORTS=('psx_game_address_in_text','psx_game_text_native_ok','psx_game_text_native_ok_full',
         'psx_game_is_function_entry','psx_dispatch_game_compiled',
         'psx_cps_mark_game','psx_cps_mark_game_ctor')


def emit(recompiler,exe,seed,folder,run,sdk,label):
    """Cache immutable raw emitter results before integration-specific renaming.

    Key the exact image/name/seed list and verified emitter revision. Validate
    every cached byte before reuse; publish a complete entry atomically.
    """
    key=hashlib.sha256(b'psx-raw-c-v1:115b1739\0'+exe.name.encode()+b'\0'+
        exe.read_bytes()+b'\0'+seed.read_bytes()).hexdigest()
    base=Path(os.environ.get('DECOMP_PSX_GENERATION_CACHE',sdk.parent/'.psx-native-cache')).resolve()
    cache=base/key[:2]/key
    try:
        metadata=json.loads((cache/'files.json').read_text(encoding='utf-8'))
        if not isinstance(metadata,dict) or not metadata:raise ValueError('empty cache')
        if exe.name+'_full.ranges' not in metadata:raise ValueError('legacy cache omits emitter sidecars')
        payload=[]
        for name,digest in metadata.items():
            path=Path(name)
            if path.name!=name or path.suffix not in ('.c','.h','.ranges'):raise ValueError('external cache file')
            data=(cache/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('changed cache file')
            payload.append((name,data))
        # A second seed pass may produce fewer shards. Do not retain a
        # previous raw shard that the verified cache no longer declares.
        for path in folder.glob(exe.name+'_full*.c'):
            if path.name not in metadata:path.unlink()
        for name,data in payload:(folder/name).write_bytes(data)
        return
    except (OSError,ValueError,TypeError):
        pass
    run([recompiler,exe,'--seeds',seed,'--out-dir',folder,'--strict','--project-root',sdk],label)
    files=sorted(p for p in folder.iterdir() if p.suffix in ('.c','.h','.ranges'))
    if not files:raise ValueError('PS1 emitter produced no source files')
    cache.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.emission-',dir=cache.parent) as temporary:
        stage=Path(temporary)/'entry';stage.mkdir()
        metadata={}
        for path in files:
            data=path.read_bytes();(stage/path.name).write_bytes(data)
            metadata[path.name]=hashlib.sha256(data).hexdigest()
        (stage/'files.json').write_text(json.dumps(metadata,sort_keys=True)+'\n',encoding='utf-8')
        try:stage.rename(cache)
        except OSError:
            if not cache.is_dir():raise
            # Upgrade legacy/corrupt entries without exposing partial files.
            # Readers verify every file; the complete index is published last.
            for path in stage.iterdir():
                if path.name!='files.json':os.replace(path,cache/path.name)
            os.replace(stage/'files.json',cache/'files.json')


_SYSCALL=re.compile(r'(?m)^([ \t]*)psx_syscall\(cpu, (\d+)\);  /\* syscall (\d+) \*/  /\* 0x([0-9A-Fa-f]{8}): 0x([0-9A-Fa-f]{8}) \*/$')
_GTE=re.compile(r'(?m)^[ \t]*gte_execute\(cpu, 0x([0-9A-Fa-f]+)\);  /\* gte cmd 0x([0-9A-Fa-f]+) \*/  /\* 0x([0-9A-Fa-f]{8}): 0x([0-9A-Fa-f]{8}) \*/$')


def native_traps(text):
    """Repair the pinned full emitter's legacy SYSCALL into its CPS ABI."""
    continuations=set()
    def replace_call(match):
        indent,code,repeated,pc,word=match.groups();address=int(pc,16);instruction=int(word,16)
        if code!=repeated or instruction&0xfc00003f!=0x0c or int(code)!=(instruction>>6)&0xfffff:
            raise ValueError('pinned SYSCALL metadata disagrees with its original instruction')
        continuations.add(address+4)
        return (indent+'#ifdef PSX_ENABLE_BLOCK_CYCLES\n'+indent+'psx_cyc_bb_defer_flush();\n'+indent+'#endif\n'+
            indent+f'cpu->pc = 0x{address:08X}u; if (psx_syscall(cpu, {code})) return;  /* original SYSCALL */\n'+
            indent+'#ifdef PSX_ENABLE_BLOCK_CYCLES\n'+indent+'psx_cyc_bb_defer_begin();\n'+indent+'#endif')
    matches=list(_SYSCALL.finditer(text))
    if len(re.findall(r'(?m)^[ \t]*psx_syscall\(cpu,',text))!=len(matches):
        raise ValueError('pinned legacy SYSCALL format differs')
    # The firmware IRQ return path inspects EPC for a COP2 command and can
    # resume at its following instruction, including inside the original CFG.
    gte=list(_GTE.finditer(text))
    if len(re.findall(r'(?m)^[ \t]*gte_execute\(cpu,',text))!=len(gte):
        raise ValueError('pinned GTE command format differs')
    for match in gte:
        command,opcode,pc,word=(int(value,16) for value in match.groups())
        if word&0xfe000000!=0x4a000000 or word&0x1ffffff!=command or word&63!=opcode:
            raise ValueError('pinned GTE metadata disagrees with its original instruction')
        continuations.add(pc+4)
    return _SYSCALL.sub(replace_call,text),continuations


def emit_native(recompiler,exe,seed,folder,run,sdk,label):
    """Emit native trap calls and interruptible instruction-cache resume entries."""
    image=exe.read_bytes();load=struct.unpack_from('<I',image,0x18)[0]
    roots={int(line,0) for line in seed.read_text().splitlines() if line.strip()}
    for _ in range(16):
        emit(recompiler,exe,seed,folder,run,sdk,label)
        sources=sorted(folder.glob(exe.name+'_full*.c'))
        rewritten=[];continuations=set()
        for path in sources:
            text,targets=native_traps(path.read_text(encoding='utf-8'))
            # A cache refill can service an interrupt inside a compiled block.
            # Returning through the BIOS resumes at this fetch PC, which need
            # not be a CFG entry. Export the actual emitted suspension sites.
            for pc in re.findall(r'(?m)^[ \t]*psx_icache_fetch\(cpu, 0x([0-9A-Fa-f]{8})u\);$',text):
                target=int(pc,16);offset=target-load
                if 4<=offset<len(image)-2048:
                    previous=struct.unpack_from('<I',image,2048+offset-4)[0]
                    op=previous>>26
                    # An IRQ in a branch delay slot resumes at the branch,
                    # not by independently executing its delay instruction.
                    if (op in (1,2,3,4,5,6,7) or
                        op==0 and previous&63 in (8,9) or
                        op in (16,17,18,19) and previous>>21&31==8):continue
                targets.add(target)
            rewritten.append((path,text));continuations.update(targets)
        emitted=set(dispatch_entries((folder/(exe.name+'_dispatch.c')).read_text(encoding='utf-8')))
        missing=continuations-emitted
        pending={target for target in missing-roots if load<=target<load+len(image)-2048 and not target&3}
        if not pending:
            for path,text in rewritten:path.write_text(text,encoding='utf-8')
            # Data-like CFG paths can end in an unsupported instruction. Keep
            # those addresses out of native dispatch and report the candidates;
            # executing one still produces a strict runtime coverage failure.
            return sorted(roots),sorted(missing)
        roots.update(pending)
        seed.write_text(''.join(f'{entry:#x}\n' for entry in sorted(roots)),encoding='utf-8')
    raise ValueError('native exception continuation discovery did not converge')


def seeds(image,info):
    payload=image[2048:];low=info['load'];high=low+len(payload)
    start=info.get('code_start',0);end=info.get('code_end',len(payload))
    found={info['entrypoint'],*info.get('native_entries',[])}
    for offset in range(start,end-3,4):
        word=struct.unpack_from('<I',payload,offset)[0]
        if word>>26==3:
            target=((low+offset+4)&0xf0000000)|((word&0x03ffffff)<<2)
            if low+start<=target<low+end:found.add(target)
    return sorted(found)


def retain_initializer(text,stem):
    old=f'__declspec(allocate(".CRT$XCU")) static void (*psx_cps_mark_{stem}_ctor)(void) = psx_cps_mark_{stem};'
    new=old.replace(' static void',' void')+'\n#if defined(_M_IX86)\n'+ \
        f'#pragma comment(linker, "/include:_psx_cps_mark_{stem}_ctor")\n#else\n'+ \
        f'#pragma comment(linker, "/include:psx_cps_mark_{stem}_ctor")\n#endif'
    if text.count(old)!=1:raise ValueError('pinned CPS initializer differs; review the native integration patch')
    return text.replace(old,new)


def dispatch_entries(text):
    """Read the pinned emitter's actual entries, including CFG continuations."""
    marker='static const PsxGameDispatchEntry k_psx_game_dispatch[] = {'
    if text.count(marker)!=1:raise ValueError('pinned PS1 entry table differs')
    table=text.split(marker,1)[1].split('};',1)[0]
    entries=[int(value,16) for value in re.findall(r'\{\s*0x([0-9a-fA-F]+)u,',table)]
    count=re.search(r'#define PSX_GAME_DISPATCH_COUNT (\d+)u',text)
    if count is None or len(entries)!=int(count[1]) or not entries or len(set(entries))!=len(entries):
        raise ValueError('pinned PS1 entry table is incomplete or ambiguous')
    return sorted(entries)


def direct_call_targets(text):
    return {int(target,16) for target in re.findall(
        r'cpu->pc = (0x[0-9a-fA-F]+)u; return;\s*/\* CPS jal -> 0x[0-9a-fA-F]+ \*/',text)}


def module(recompiler,disc,folder,run,sdk):
    folder.mkdir(parents=True,exist_ok=True)
    image=disc['image'];info=disc['info'];ordinal=disc.get('module_index',disc['index']);prefix=f'decomp_m{ordinal}_'
    exe=folder/(Path(disc.get('boot','PSX.EXE')).name or 'PSX.EXE');exe.write_bytes(image)
    entries=seeds(image,info)
    (folder/'seeds.txt').write_text(''.join(f'{entry:#x}\n' for entry in entries),encoding='utf-8')
    entries,uncompiled=emit_native(recompiler,exe,folder/'seeds.txt',folder,run,sdk,
         'PS1 static C generation for disc '+str(disc['index']))
    dispatch=folder/(exe.name+'_dispatch.c')
    original=dispatch.read_text(encoding='utf-8')
    emitted_entries=dispatch_entries(original)
    original=retain_initializer(original,'game')
    if original.count('    entry->fn(cpu);')!=1:raise ValueError('pinned native dispatch accounting site differs')
    original=original.replace('    entry->fn(cpu);',
        f'    extern uint64_t decomp_native_dispatches, decomp_module_dispatches[];\n'
        f'    decomp_native_dispatches++;decomp_module_dispatches[{ordinal-1}]++;\n    entry->fn(cpu);')
    dispatch.write_text(original,encoding='utf-8')
    external_calls=set()
    physical_low=info['load']&0x1fffffff
    for path in folder.iterdir():
        if path.suffix not in ('.c','.h'):continue
        text=path.read_text(encoding='utf-8')
        for address in direct_call_targets(text):
            if not physical_low<=(address&0x1fffffff)<physical_low+len(image)-2048:
                external_calls.add(address)
        for name in sorted(EXPORTS,key=len,reverse=True):text=re.sub(r'\b'+name+r'\b',prefix+name,text)
        text=re.sub(r'\b(?:func_|psx_alias_body_)[0-9a-fA-F]{8}\b',lambda match:prefix+match[0],text)
        for name in ('dirty_ram_text_native_ok_ranges_from','dirty_ram_text_native_ok_ranges'):
            text=re.sub(r'\b'+name+r'\b',prefix+name,text)
        path.write_text(text,encoding='utf-8')
    # Each emitted CFG is checked against ITS image. A current-disc index or
    # one boot-image snapshot cannot identify code after a tray change/overlay.
    payload=image[2048:];low=info['load']&0x1fffffff
    array=',\n'.join(','.join(str(b) for b in payload[i:i+32]) for i in range(0,len(payload),32))
    guard=f'''
#include <string.h>
#include <stdlib.h>
extern unsigned char *g_psx_ram;
static const unsigned char {prefix}image[]={{
{array}
}};
int {prefix}dirty_ram_text_native_ok_ranges_from(const uint32_t *ranges,uint32_t count,uint32_t pc) {{
    (void)pc;
    if(!ranges||!count)return 0;
#ifndef DECOMP_PSX_NATIVE_ONLY
    /* Native players reject interpreter mode once during startup. The
       reference player retains its live mode switch. */
    const char *force=getenv("PSX_FORCE_INTERP");
    if(force&&*force&&*force!='0')return 0;
#endif
    for(uint32_t i=0;i<count;i++) {{
        uint32_t address=ranges[i*2]&0x1fffffffu,length=ranges[i*2+1];
        if(address<{low}u||address-{low}u>sizeof({prefix}image)||
           !length||length>sizeof({prefix}image)-(address-{low}u))return 0;
        if(memcmp(g_psx_ram+address,{prefix}image+address-{low}u,length))return 0;
    }}
    return 1;
}}
int {prefix}dirty_ram_text_native_ok_ranges(const uint32_t *ranges,uint32_t count) {{
    return {prefix}dirty_ram_text_native_ok_ranges_from(ranges,count,0);
}}
'''
    with dispatch.open('a',encoding='utf-8') as stream:stream.write(guard)
    return dict(index=ordinal,disc=disc['index'],prefix=prefix,seeds=len(entries),
                external_calls=sorted(external_calls),
                uncompiled_trap_continuations=uncompiled,
                entries=emitted_entries,load_address=low,image_size=len(payload),
                image_sha256=hashlib.sha256(image).hexdigest(),
                dispatch_sha256=hashlib.sha256(dispatch.read_bytes()).hexdigest(),
                **({'source':disc['source']} if 'source' in disc else {}))


def close_resident_calls(recompiler,originals,modules,run,sdk,log=lambda value:None,*,additional_calls=()):
    """Close emitted cross-image calls over boot code and loaded libraries."""
    attempted={}
    for _ in range(16):
        calls={address&0x1fffffff for item in modules for address in item['external_calls']}
        calls.update(address&0x1fffffff for address in additional_calls)
        changed=False
        for position,(item,folder) in enumerate(originals):
            info=item['info'];low=info['load']&0x1fffffff;size=len(item['image'])-2048
            ordinal=item['module_index'];compiled=modules[ordinal-1]
            tried=attempted.setdefault(ordinal,set())
            candidates={info['load']+address-low for address in calls if low<=address<low+size}
            missing=candidates-set(compiled['entries'])-tried
            if not missing:continue
            tried.update(missing);changed=True
            updated={**item,'info':{**info,'native_entries':sorted(set(info.get('native_entries',[]))|missing)}}
            log(f'Compiling {len(missing)} external call entries for image {ordinal}, disc {item["index"]}')
            # The exporter owns this newly generated tree. Keep nested overlay
            # directories; replace only this image's flat output files.
            for path in folder.iterdir():
                if path.is_file():path.unlink()
            regenerated=module(recompiler,updated,folder,run,sdk)
            compiled.update(regenerated)
            originals[position]=(updated,folder)
        if not changed:
            return [dict(module_index=ordinal,seeded_calls=sorted(entries),
                uncompiled_calls=sorted(entries-set(modules[ordinal-1]['entries'])))
                for ordinal,entries in sorted(attempted.items()) if entries]
    raise ValueError('native cross-image call discovery did not converge')


def registry(modules,path,*,copied=False):
    lines=['#include "cpu_state.h"','#include <stdint.h>',
           'uint64_t decomp_native_dispatches=0;',f'const unsigned decomp_module_count={len(modules)};',
           f'uint64_t decomp_module_dispatches[{len(modules)}]={{0}};']
    if copied:
        lines.extend(['extern int decomp_psx_copy_valid(uint32_t);',
                      'extern int decomp_psx_dispatch_copy(CPUState*,uint32_t);'])
    copy_valid='decomp_psx_copy_valid(address)' if copied else '0'
    copy_dispatch='decomp_psx_dispatch_copy(cpu,address)' if copied else '0'
    for item in modules:
        prefix=item['prefix']
        lines.append(f'extern int {prefix}psx_dispatch_game_compiled(CPUState*,uint32_t);')
        for name in EXPORTS[:4]:lines.append(f'extern int {prefix}{name}(uint32_t);')
    lines.append('typedef struct {int (*dispatch)(CPUState*,uint32_t);int (*valid)(uint32_t);'
                 'int (*full)(uint32_t);} DecompModule;\nstatic const DecompModule modules[]={')
    for item in modules:
        prefix=item['prefix']
        lines.append('{'+','.join(prefix+name for name in
                     ('psx_dispatch_game_compiled','psx_game_text_native_ok','psx_game_text_native_ok_full'))+'},')
    lines.append('};')
    candidates={}
    ranges=[]
    for index,item in enumerate(modules):
        for address in item['entries']:candidates.setdefault(address,[]).append(index)
        low=item['load_address'];ranges.append((low,low+item['image_size']))
    rows=[];owners=[]
    for address,indices in sorted(candidates.items()):
        rows.append(f'{{0x{address:08x}u,{len(owners)}u,{len(indices)}u}},')
        owners.extend(indices)
    lines.extend(['typedef struct {uint32_t pc,first,count,hint;} DecompEntry;',
                  'static DecompEntry entries[]={',*rows,'};',
                  'static const uint32_t owners[]={'+','.join(map(str,owners))+'};',
                  'static uint32_t page_hints[512];',
                  '''static DecompEntry *lookup(uint32_t address){
    uint32_t low=0,high=(uint32_t)(sizeof(entries)/sizeof(entries[0]));
    while(low<high){uint32_t mid=low+(high-low)/2;
        if(entries[mid].pc<address)low=mid+1;else high=mid;}
    return low<sizeof(entries)/sizeof(entries[0])&&entries[low].pc==address?entries+low:NULL;
}'''])
    for name,member in (('psx_dispatch_game_compiled','dispatch'),('psx_game_text_native_ok','valid'),
                        ('psx_game_text_native_ok_full','full'),('psx_game_is_function_entry','valid')):
        dispatch=member=='dispatch';arguments='CPUState *cpu,uint32_t address' if dispatch else 'uint32_t address'
        fallback=copy_dispatch if dispatch else copy_valid
        call=lambda owner:f'modules[{owner}].{member}('+('cpu,' if dispatch else '')+'address)'
        # Hints change lookup order only. Every hit still calls the original
        # immutable-footprint guard; overwritten code immediately misses.
        lines.append(f'''int {name}({arguments}){{
    DecompEntry *entry=lookup(address);if(!entry)return {fallback};
    uint32_t page=(address&0x1fffffffu)>>12,cached=entry->hint;
    if({call('cached')}){{if(page<512u)page_hints[page]=cached;return 1;}}
    uint32_t nearby=page<512u?page_hints[page]:cached;
    if(nearby!=cached&&{call('nearby')}){{entry->hint=nearby;return 1;}}
    for(uint32_t i=0;i<entry->count;i++){{
        uint32_t owner=owners[entry->first+i];
        if(owner==cached||owner==nearby)continue;
        if({call('owner')}){{entry->hint=owner;if(page<512u)page_hints[page]=owner;return 1;}}
    }}
    return {fallback};
}}''')
    merged=[]
    for low,high in sorted(ranges):
        if merged and low<=merged[-1][1]:merged[-1]=(merged[-1][0],max(high,merged[-1][1]))
        else:merged.append((low,high))
    covered='||'.join(f'(physical>={low}u&&physical<{high}u)' for low,high in merged)
    lines.append('int psx_game_address_in_text(uint32_t address){uint32_t physical=address&0x1fffffffu;'
                 'return '+covered+'||'+copy_valid+';}')
    lines.append(r'''
/* OpenBIOS 55fbf046: loadSystemCnf zeroes configuration before parsing.
 * Its const-propagated findWordItem takes (destination, key). Restore the
 * link-script defaults for omitted fields; an explicit field still wins.
 * Restrict this ABI adaptation to that pinned helper and ordinary memory. */
void decomp_openbios_config_defaults(CPUState *cpu) {
    if(cpu->pc && (cpu->pc&0x1fffffffu)!=0x1fc06ae4u)return;
    uint32_t target=cpu->gpr[4],name=cpu->gpr[5],phys=target&0x1fffffffu;
    if((target&3u)||phys>0x1ffffcu)return;
    char key[6]={0};
    for(unsigned i=0;i<5;i++) {
        uint32_t p=(name+i)&0x1fffffffu;
        if(p>=0x200000u && !(p>=0x1fc00000u&&p<0x1fc80000u))return;
        key[i]=(char)cpu->read_byte(name+i);if(!key[i])break;
    }
    uint32_t value=0;
    if(!strcmp(key,"TCB"))value=4;
    else if(!strcmp(key,"EVENT"))value=16;
    else if(!strcmp(key,"STACK"))value=0x801fff00u;
    if(value && cpu->read_word(target)==0)cpu->write_word(target,value);
}
''')
    lines.insert(1,'#include <string.h>')
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
