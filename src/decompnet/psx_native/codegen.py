"""Static modules with independent byte identities, including shared disc addresses."""
import hashlib
import json
from pathlib import Path
import re
import struct

EXPORTS=('psx_game_address_in_text','psx_game_text_native_ok','psx_game_text_native_ok_full',
         'psx_game_is_function_entry','psx_dispatch_game_compiled',
         'psx_cps_mark_game','psx_cps_mark_game_ctor')


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


def module(recompiler,disc,folder,run,sdk):
    folder.mkdir(parents=True)
    image=disc['image'];info=disc['info'];ordinal=disc.get('module_index',disc['index']);prefix=f'decomp_m{ordinal}_'
    exe=folder/(Path(disc.get('boot','PSX.EXE')).name or 'PSX.EXE');exe.write_bytes(image)
    entries=seeds(image,info)
    (folder/'seeds.txt').write_text(''.join(f'{entry:#x}\n' for entry in entries),encoding='utf-8')
    run([recompiler,exe,'--seeds',folder/'seeds.txt','--out-dir',folder,'--strict','--project-root',sdk],
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
    for path in folder.iterdir():
        if path.suffix not in ('.c','.h'):continue
        text=path.read_text(encoding='utf-8')
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
    const char *force=getenv("PSX_FORCE_INTERP");
    if(force&&*force&&*force!='0')return 0;
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
                entries=emitted_entries,load_address=low,image_size=len(payload),
                image_sha256=hashlib.sha256(image).hexdigest(),
                dispatch_sha256=hashlib.sha256(dispatch.read_bytes()).hexdigest(),
                **({'source':disc['source']} if 'source' in disc else {}))


def registry(modules,path):
    lines=['#include "cpu_state.h"','#include <stdint.h>',
           'uint64_t decomp_native_dispatches=0;',f'const unsigned decomp_module_count={len(modules)};',
           f'uint64_t decomp_module_dispatches[{len(modules)}]={{0}};']
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
    lines.extend(['typedef struct {uint32_t pc,first,count;} DecompEntry;',
                  'static const DecompEntry entries[]={',*rows,'};',
                  'static const uint32_t owners[]={'+','.join(map(str,owners))+'};',
                  '''static const DecompEntry *lookup(uint32_t address){
    uint32_t low=0,high=(uint32_t)(sizeof(entries)/sizeof(entries[0]));
    while(low<high){uint32_t mid=low+(high-low)/2;
        if(entries[mid].pc<address)low=mid+1;else high=mid;}
    return low<sizeof(entries)/sizeof(entries[0])&&entries[low].pc==address?entries+low:NULL;
}
int psx_dispatch_game_compiled(CPUState *cpu,uint32_t address){
    const DecompEntry *entry=lookup(address);if(!entry)return 0;
    for(uint32_t i=0;i<entry->count;i++)
        if(modules[owners[entry->first+i]].dispatch(cpu,address))return 1;
    return 0;
}'''])
    for name,member in (('psx_game_text_native_ok','valid'),('psx_game_text_native_ok_full','full'),
                        ('psx_game_is_function_entry','valid')):
        # An indexed candidate still checks its whole immutable footprint.
        lines.append(f'int {name}(uint32_t address){{\n'
            'const DecompEntry *entry=lookup(address);if(!entry)return 0;\n'
            'for(uint32_t i=0;i<entry->count;i++)\n'
            f'if(modules[owners[entry->first+i]].{member}(address))return 1;\nreturn 0;}}')
    merged=[]
    for low,high in sorted(ranges):
        if merged and low<=merged[-1][1]:merged[-1]=(merged[-1][0],max(high,merged[-1][1]))
        else:merged.append((low,high))
    covered='||'.join(f'(physical>={low}u&&physical<{high}u)' for low,high in merged)
    lines.append('int psx_game_address_in_text(uint32_t address){uint32_t physical=address&0x1fffffffu;'
                 'return '+covered+';}')
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
