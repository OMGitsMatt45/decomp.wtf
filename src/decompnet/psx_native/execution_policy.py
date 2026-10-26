"""Keep the pinned native dispatch conductor while excluding its ISA engine."""
import re

from .copies import _C_TOKEN


def _function(text,name):
    matches=list(re.finditer(r'\b'+re.escape(name)+r'\([^;{}]*?\)\s*\{',text))
    if len(matches)!=1:
        raise ValueError('pinned PS1 execution function differs: '+name)
    match=matches[0];opening=match.end()-1;depth=0
    for token in _C_TOKEN.finditer(text,opening):
        if token[0]=='{':depth+=1
        elif token[0]=='}':
            depth-=1
            if depth==0:return match.start(),opening,token.start()
    raise ValueError('unterminated pinned PS1 execution function: '+name)


def _select(text,name,native):
    _,opening,closing=_function(text,name)
    original=text[opening+1:closing]
    return text[:opening+1]+'\n#ifdef DECOMP_PSX_NATIVE_ONLY\n'+native+\
        '\n#else\n'+original+'\n#endif\n'+text[closing:]


def patch(text):
    marker='#include "cpu_state.h"'
    if text.count(marker)!=1:
        raise ValueError('pinned PS1 CPU include differs')
    text=text.replace(marker,marker+'\n#include <stdio.h>\n'
        '#ifdef DECOMP_PSX_NATIVE_ONLY\n'
        'extern void decomp_psx_missing_native(CPUState*,uint32_t);\n#endif')
    # Keep the original event, CPS return, load-delay and observer interfaces.
    # Only the actual instruction engine is absent from the native build.
    start,_,closing=_function(text,'exec_one_fetched_inner')
    start=text.rfind('\n',0,start)+1
    text=text[:start]+'#ifndef DECOMP_PSX_NATIVE_ONLY\n'+text[start:closing+1]+\
        '\n#endif\n'+text[closing+1:]
    text=_select(text,'exec_one',
        '    (void)next_pc_out;decomp_psx_missing_native(cpu,pc);return 0;')
    text=_select(text,'exec_one_fetched',
        '    (void)insn;(void)next_pc_out;decomp_psx_missing_native(cpu,pc);return 0;')
    _,opening,closing=_function(text,'dirty_ram_dispatch_inner')
    original=text[opening+1:closing]
    boundary='/* Every exit retires any deferred load writeback:'
    if original.count(boundary)!=1:
        raise ValueError('pinned native PS1 dispatch boundary differs')
    prefix=original.split(boundary,1)[0]
    native='''
    if(stop_addr&&addr==stop_addr){cpu->pc=addr;return 1;}
'''+prefix+'''
    decomp_psx_missing_native(cpu,addr);return 0;
'''
    text=_select(text,'dirty_ram_dispatch_inner',native)
    text=_select(text,'psx_slice_block_impl',
        '    (void)cpu;(void)block_addr;(void)bcyc;(void)side_effects;return 0;')
    text=_select(text,'psx_precise_slice_init_from_env','''
    const char *value=getenv("PSX_PRECISE_SLICE");
    if(value&&value[0]=='1'){
        fputs("PSX_PRECISE_SLICE requires the optional ps1_probe reference target.\\n",stderr);
        exit(2);
    }
    g_psx_precise_slice=0;
''')
    return text
