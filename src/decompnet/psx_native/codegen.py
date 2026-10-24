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
    found={info['entrypoint']}
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
        text=re.sub(r'\bfunc_[0-9a-fA-F]{8}\b',lambda match:prefix+match[0],text)
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
                image_sha256=hashlib.sha256(image).hexdigest(),
                dispatch_sha256=hashlib.sha256(dispatch.read_bytes()).hexdigest())


def registry(modules,path):
    lines=['#include "cpu_state.h"','#include <stdint.h>',
           'uint64_t decomp_native_dispatches=0;',f'const unsigned decomp_module_count={len(modules)};',
           f'uint64_t decomp_module_dispatches[{len(modules)}]={{0}};']
    for item in modules:
        prefix=item['prefix']
        lines.append(f'extern int {prefix}psx_dispatch_game_compiled(CPUState*,uint32_t);')
        for name in EXPORTS[:4]:lines.append(f'extern int {prefix}{name}(uint32_t);')
    lines.append('int psx_dispatch_game_compiled(CPUState *cpu,uint32_t address){')
    for item in modules:
        lines.append(f'if({item["prefix"]}psx_dispatch_game_compiled(cpu,address))return 1;')
    lines.append('return 0;}')
    for name in EXPORTS[:4]:
        # Entry classification also uses immutable bytes; never classify an
        # address as native merely because another disc uses the same address.
        variant='psx_game_text_native_ok' if name=='psx_game_is_function_entry' else name
        calls='||'.join(f'{item["prefix"]}{variant}(address)' for item in modules)
        lines.append(f'int {name}(uint32_t address){{return {calls};}}')
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
