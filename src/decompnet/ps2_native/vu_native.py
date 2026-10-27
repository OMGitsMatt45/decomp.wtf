"""Native-only VU pair selection with the pinned pipeline and math contracts."""
import json
from pathlib import Path
import re

from ..pc import PCError
from .runtime_patch import replace

_TOKENS=re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')


def _body(text,name):
    matches=list(re.finditer(r'\bvoid VU1Interpreter::'+re.escape(name)+r'\([^;{}]*\)\s*\{',text))
    if len(matches)!=1:raise PCError('pinned VU execution body differs: '+name)
    opening=matches[0].end()-1;depth=0
    for token in _TOKENS.finditer(text,opening):
        if token[0]=='{':depth+=1
        elif token[0]=='}':
            depth-=1
            if not depth:return opening,token.start()
    raise PCError('unterminated pinned VU execution body')


NATIVE_BODY=r'''
    m_activeVuData=vuData;m_activeVuDataSize=dataSize;m_activeGs=&gs;m_activeMemory=memory;
    const int previous=std::fegetround();const bool rounded=std::fesetround(FE_TOWARDZERO)==0;
    struct Rounding {int previous;bool rounded;~Rounding(){if(rounded&&previous!=-1)std::fesetround(previous);}} rounding{previous,rounded};
    const uint64_t budgetEnd=m_cycle+maxCycles;bool programEnded=false;
    commitReadyPipelines();
    while(!programEnded&&m_cycle<budgetEnd&&!m_stopRequested){
        const uint32_t pc=m_state.pc;
        DecompVuFunction function=nullptr;
        if(!(pc&7u)&&pc<=codeSize&&codeSize-pc>=8u){
            uint64_t word;std::memcpy(&word,vuCode+pc,8);
            function=decomp_find_vu_pair(word,m_unit==Unit::VU1);
        }
        if(!function){
            decomp_ps2::execution::vu_gap(m_unit==Unit::VU1?1u:0u,pc);
            std::fprintf(stderr,"decomp.wtf: missing native VU%u pair at %04x\n",m_unit==Unit::VU1?1u:0u,pc);
            m_stopRequested=true;break;
        }
        programEnded=function(*this,budgetEnd,codeSize);
    }
    if(programEnded){
        flushPipelines();m_state.ebit=false;m_state.haltAfterDelaySlot=false;
        m_pendingHaltD=false;m_pendingHaltT=false;
    }
    m_state.cycles=m_cycle;
'''


def patch(root):
    runtime=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime'
    folder=runtime/'src/lib/vu'
    for name,target in (('vu_catalog.hpp','decomp_vu_catalog.hpp'),('vu_execution.hpp','decomp_vu_execution.hpp'),
                       ('vu_native.inl','decomp_vu_native.inl')):
        (folder/target).write_bytes(Path(__file__).with_name(name).read_bytes())
    replace(folder/'ps2_vu1_program.h','struct Access\n{',
        '''struct Access
{
    template <VU1Interpreter::Unit unit,uint64_t Word>
    static bool decompNativePair(VU1Interpreter&,uint64_t,uint32_t);
''')
    core=folder/'ps2_vu1_core.cpp';text=core.read_text();opening,closing=_body(text,'run')
    original=text[opening+1:closing]
    accounting=r'''
    const uint64_t nativeBefore=m_compiledPairsExecuted,interpretedBefore=m_interpretedPairsExecuted;
    const auto account=[&](){
        decomp_ps2::execution::vu_native_pairs.fetch_add(m_compiledPairsExecuted-nativeBefore,std::memory_order_relaxed);
        decomp_ps2::execution::vu_interpreted_pairs.fetch_add(m_interpretedPairsExecuted-interpretedBefore,std::memory_order_relaxed);
    };
    struct Accounting {decltype(account)& done;~Accounting(){done();}} accounting{account};
'''
    text=text[:opening+1]+accounting+'\n#ifdef DECOMP_PS2_NATIVE_VU\n'+NATIVE_BODY+'\n#else\n'+original+'\n#endif\n'+text[closing:]
    text='#include "decomp_vu_catalog.hpp"\n#include "decomp_vu_execution.hpp"\n'+text
    core.write_text(text)
    replace(core,'    if (m_unit == Unit::VU1)\n        ps2_vu_program::forgetRoutines();',
        '#ifndef DECOMP_PS2_NATIVE_VU\n    if (m_unit == Unit::VU1)\n        ps2_vu_program::forgetRoutines();\n#endif')
    replace(core,'void VU1Interpreter::reportReservedInstruction(bool upper, uint32_t instruction)\n{',
        '''void VU1Interpreter::reportReservedInstruction(bool upper, uint32_t instruction)
{
#ifdef DECOMP_PS2_NATIVE_VU
    decomp_ps2::execution::vu_gap(m_unit==Unit::VU1?1u:0u,m_state.pc);
#endif''')
    lower=folder/'ps2_vu1_lower.inl';text=lower.read_text()
    call='            ps2_vu_program::noteJump(memory, target);'
    if text.count(call)!=2:raise PCError('pinned VU jump observer differs')
    lower.write_text(text.replace(call,'#ifndef DECOMP_PS2_NATIVE_VU\n'+call+'\n#endif'))
    # The primary executable has neither dynamic opcode entry points nor the
    # whole-program path's dynamic arithmetic escape. Reference builds keep them.
    for name in ('ps2_vu1_upper.cpp','ps2_vu1_lower.cpp','ps2_vu1_program.cpp'):
        path=folder/name;path.write_text('#ifndef DECOMP_PS2_NATIVE_VU\n'+path.read_text()+'\n#endif\n')


def generate(catalog,folder):
    folder=Path(folder);folder.mkdir(parents=True)
    words=sorted(catalog.words);declarations=[];entries=[]
    # Each pair instantiates both hardware units and the pipeline conductor.
    # Small translation units bound compiler memory for retail-sized catalogs.
    batch=8
    for start in range(0,len(words),batch):
        text=['// Generated native operations from original input bytes.',
              '#include "decomp_vu_catalog.hpp"','#include "decomp_vu_native.inl"']
        for index,word in enumerate(words[start:start+batch],start):
            for unit in (0,1):
                name=f'decomp_vu{unit}_pair{index}'
                declaration=f'bool {name}(VU1Interpreter&,uint64_t,uint32_t);';declarations.append(declaration)
                text.append(f'bool {name}(VU1Interpreter& vu,uint64_t budget,uint32_t size){{'
                    f'return ps2_vu_program::Access::decompNativePair<VU1Interpreter::Unit::VU{unit},0x{word:016x}ull>(vu,budget,size);}}')
            entries.append('{'+f'0x{word:016x}ull,decomp_vu0_pair{index},decomp_vu1_pair{index}'+'}')
        (folder/f'pairs{start//batch}.cpp').write_text('\n'.join(text)+'\n')
    text=['#include "decomp_vu_catalog.hpp"','#include <algorithm>',*declarations]
    if entries:
        text.extend(['namespace {struct Entry{uint64_t word;DecompVuFunction unit0,unit1;};',
            'const Entry entries[]={',',\n'.join(entries),'};}','''
DecompVuFunction decomp_find_vu_pair(uint64_t word,bool unit1){
    const auto *found=std::lower_bound(std::begin(entries),std::end(entries),word,
        [](const Entry &entry,uint64_t value){return entry.word<value;});
    return found!=std::end(entries)&&found->word==word?(unit1?found->unit1:found->unit0):nullptr;
}'''])
    else:text.append('DecompVuFunction decomp_find_vu_pair(uint64_t,bool){return nullptr;}')
    (folder/'catalog.cpp').write_text('\n'.join(text)+'\n')
    record=dict(pair_count=len(words),programs=catalog.records)
    (folder/'catalog.json').write_text(json.dumps(record,indent=2)+'\n')
    return record
