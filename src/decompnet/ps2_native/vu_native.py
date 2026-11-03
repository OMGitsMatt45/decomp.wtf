"""Native-only VU pair selection with the pinned pipeline and math contracts."""
import json
from pathlib import Path
import re

from ..pc import PCError
from .runtime_patch import replace
from . import vu_normalized_inputs, vu_plain_sse

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
#ifdef DECOMP_PS2_NATIVE_VU_PROGRAMS
    static const bool wholePrograms=[](){const char *value=std::getenv("DECOMP_PS2_VU_PROGRAMS");return !value||std::strcmp(value,"0")!=0;}();
    const bool trackedCode=memory&&m_unit==Unit::VU1&&vuCode==memory->getVU1Code()&&codeSize==PS2_VU1_CODE_SIZE;
    if(wholePrograms&&trackedCode&&budgetEnd-m_cycle>=ps2_vu_program::kMinimumBudget&&ps2_vu_program::Access::drained(*this)){
        if(const auto routine=ps2_vu_program::find(vuCode,codeSize,m_state.pc,memory->getVU1CodeGeneration())){
            const auto programBefore=m_compiledPairsExecuted;
            programEnded=ps2_vu_program::run(*this,vuCode,codeSize,budgetEnd,routine);
            decomp_ps2::execution::vu_native_programs.fetch_add(1,std::memory_order_relaxed);
            decomp_ps2::execution::vu_native_program_pairs.fetch_add(m_compiledPairsExecuted-programBefore,std::memory_order_relaxed);
        }else ps2_vu_program::recordMissing(vuCode,codeSize,m_state.pc);
    }
#endif
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


def _shared_pipeline(folder):
    """Retain pinned ordering and specialize fixed pair metadata at compile time."""
    text=(folder/'ps2_vu1_exec.inl').read_text()
    signature='PS2_VU_FORCE_INLINE bool VU1Interpreter::runDecodedPair('
    if text.count(signature)!=1:raise PCError('pinned VU pipeline conductor differs')
    opening=text.index('{',text.index(signature));closing=text.index('\n}\n',opening)
    body=text[opening+1:closing]
    upper='if constexpr (compiled) execUpperInline(decoded.upper);\n        else execUpper(decoded.upper);'
    lower='''if constexpr (compiled)
            execLowerInline(decoded.lower, m_activeVuData, m_activeVuDataSize, *m_activeGs, m_activeMemory, decoded.upper);
        else
            execLower(decoded.lower, m_activeVuData, m_activeVuDataSize, *m_activeGs, m_activeMemory, decoded.upper);'''
    if body.count(upper)!=1 or body.count(lower)!=1:raise PCError('pinned VU operation callbacks differ')
    body=body.replace(upper,'upperOperation(vu);').replace(lower,'lowerOperation(vu);')
    body=re.sub(r'\bcompiled\b','true',body)
    body=re.sub(r'\bm_\w+',lambda match:'vu.'+match[0],body)
    members=('reportReservedInstruction','calculatePairReadyCycleInline','calculatePairReadyCycle',
        'advanceTo','normalizeOperand','queueVfWrite','queueAccWrite','queueViWrite',
        'markPairWritesInline','markPairWrites','recordViWriteForBranch','microAddressMask','advanceOneCycle')
    body=re.sub(r'\b('+ '|'.join(members)+r')\b',lambda match:'vu.'+match[0],body)
    body=re.sub(r'\b(VfAccess|PipelineBranch|kAccForwardLatency)\b',lambda match:'VU1Interpreter::'+match[0],body)
    (folder/'decomp_vu_pipeline.cpp').write_text('''// SPDX-License-Identifier: GPL-3.0-only
// Pinned hardware pipeline conductor. Operation callbacks are selected at export time.
#include "ps2_vu1_exec.inl"
#include "ps2_vu1_program.h"
bool ps2_vu_program::Access::decompRunPair(VU1Interpreter &vu,
    const VU1Interpreter::DecodedInstructionPair &decoded,DecompOperation upperOperation,
    DecompOperation lowerOperation,uint64_t budgetEnd,uint32_t codeSize) {
'''+body+'\n}\n')
    specialized=body.replace('upperOperation(vu);','decompUpper<uint32_t(Word>>32u)>(vu);')
    specialized=specialized.replace('lowerOperation(vu);','decompLower<Word>(vu);')
    (folder/'decomp_vu_pair_pipeline.inl').write_text(
        '// SPDX-License-Identifier: GPL-3.0-only\n'
        '// Same pinned conductor; decoded pair metadata and operation calls are compile-time constants.\n'+specialized+'\n')


def flag_queue_bounds(header):
    # Forming tail + requested slots is undefined when the queue needs room.
    # Compare the available distance between pointers inside the array instead.
    replace(header,'        if (m_flagTail + 2u * Pairs > m_run.m_flags.data() + Run::kFlagSlots) [[unlikely]]',
        '        if (m_run.m_flags.data() + Run::kFlagSlots - m_flagTail < static_cast<std::ptrdiff_t>(2u * Pairs)) [[unlikely]]')


def _program_support(folder):
    """Keep whole-program operations static, including exceptional arithmetic."""
    header=folder/'ps2_vu1_program.h'
    flag_queue_bounds(header)
    replace(header,'void forgetRoutines();',
        'void forgetRoutines();\n#ifdef DECOMP_PS2_NATIVE_VU\nconst Entry *nativeEntries(size_t &count);\n#endif')
    replace(header,'    void exactUpper(uint32_t upper);',r'''#ifdef DECOMP_PS2_NATIVE_VU
    template<uint32_t Upper> void exactUpper(){
        constexpr uint32_t fs=(Upper>>11u)&31u,ft=(Upper>>16u)&31u;
        const UpperInputs inputs{m_state.vf[fs],m_state.vf[ft],m_state.acc,m_state.i,m_state.q};
        m_upper={};ps2_vu_detail::upper::computeUpper(Upper,inputs,m_upper);
    }
#else
    void exactUpper(uint32_t upper);
#endif''')
    replace(header,'        m_run.exactUpper(Upper);',r'''#ifdef DECOMP_PS2_NATIVE_VU
        m_run.exactUpper<Upper>();
#else
        m_run.exactUpper(Upper);
#endif''')
    implementation=folder/'ps2_vu1_program.cpp';text=implementation.read_text()
    opening=text.index('const Entry kEntries[] = {');closing=text.index('\n};',opening)+3
    text=text[:opening]+'#ifndef DECOMP_PS2_NATIVE_VU\n'+text[opening:closing]+'\n#endif'+text[closing:]
    old='''    const Entry *const begin = std::begin(kEntries);
    const Entry *const end = std::end(kEntries) - 1;'''
    if text.count(old)!=1:raise PCError('pinned VU program registry differs')
    text=text.replace(old,'''#ifdef DECOMP_PS2_NATIVE_VU
    size_t count=0;const Entry *const begin=nativeEntries(count);
    if(!begin||!count){slot={code,generation,epoch,nullptr,true};return nullptr;}
    const Entry *const end=begin+count;
#else
'''+old+'\n#endif')
    opening=text.index('void Run::exactUpper(uint32_t upper)');closing=text.index('\n}\n',opening)+3
    text=text[:opening]+'#ifndef DECOMP_PS2_NATIVE_VU\n'+text[opening:closing]+'\n#endif\n'+text[closing:]
    implementation.write_text(text)
    reduce_clip_flag_batches(implementation)
    retire_saturated_fmac(implementation)


def retire_saturated_fmac(implementation):
    marker = '    // A CLIP at the end of an FMAC batch'
    replace(implementation, marker, '''    // When Z/S/U/O are all sticky and FSSET is absent, earlier FMAC results
    // cannot change status. Only the newest FMAC and CLIP are observable.
    const uint32_t finalWrites = end[-1].writes;
    if (m_fssetQueued == 0u && (m_state.status & 0x3C0u) == 0x3C0u &&
        (finalWrites == 3u || finalWrites == 8u))
    {
        const auto previousWith = [&](uint32_t mask) -> const PendingFlags * {
            for (auto *entry = end - 1; entry != head;)
                if ((--entry)->writes & mask)
                    return entry;
            return nullptr;
        };
        const bool lastIsClip = finalWrites == 8u;
        const auto *clip = lastIsClip ? end - 1 : previousWith(8u);
        const auto *fmac = lastIsClip ? previousWith(1u) : end - 1;
        if (clip)
            m_state.clip = clip->value;
        if (fmac)
        {
            m_state.mac = fmac->value;
            m_state.status = (m_state.status & 0xFF0u) | statusOf(fmac->value);
        }
        return end;
    }

'''+marker)


def reduce_clip_flag_batches(implementation):
    marker='    // Usually every one is an FMAC result:'
    replace(implementation,marker,'''    // A CLIP at the end of an FMAC batch would send the batch through both
    // reduction loops. Fold the FMAC prefix first and publish the last CLIP
    // separately. They update disjoint parts of the guest state.
    if (end[-1].writes == 8u)
    {
        PendingFlags *clipStart = end - 1;
        while (clipStart != head && clipStart[-1].writes == 8u)
            --clipStart;
        uint32_t conditions = 0u, other = 0u;
        for (const PendingFlags *entry = head; entry != clipStart; ++entry)
        {
            conditions |= entry->value | entry->sticky;
            other |= entry->writes ^ 3u;
        }
        if (other == 0u)
        {
            if (head != clipStart)
            {
                m_state.mac = clipStart[-1].value;
                const uint32_t now = statusOf(m_state.mac);
                m_state.status = (m_state.status & 0xFF0u) | now | ((now | statusOf(conditions)) << 6u);
            }
            m_state.clip = end[-1].value;
            return end;
        }
    }

'''+marker)


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
    template <uint32_t Instruction> static void decompUpper(VU1Interpreter&);
    template <uint64_t Word> static void decompLower(VU1Interpreter&);
    using DecompOperation=void(*)(VU1Interpreter&);
    static bool decompRunPair(VU1Interpreter&,const VU1Interpreter::DecodedInstructionPair&,
                              DecompOperation,DecompOperation,uint64_t,uint32_t);
''')
    _shared_pipeline(folder)
    _program_support(folder)
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
        '#if !defined(DECOMP_PS2_NATIVE_VU) || defined(DECOMP_PS2_NATIVE_VU_PROGRAMS)\n    if (m_unit == Unit::VU1)\n        ps2_vu_program::forgetRoutines();\n#endif')
    replace(core,'void VU1Interpreter::reportReservedInstruction(bool upper, uint32_t instruction)\n{',
        '''void VU1Interpreter::reportReservedInstruction(bool upper, uint32_t instruction)
{
#ifdef DECOMP_PS2_NATIVE_VU
    decomp_ps2::execution::vu_gap(m_unit==Unit::VU1?1u:0u,m_state.pc);
#endif''')
    lower=folder/'ps2_vu1_lower.inl';text=lower.read_text()
    call='        if (m_unit == Unit::VU1)\n            ps2_vu_program::noteJump(memory, target);'
    if text.count(call)!=2:raise PCError('pinned VU jump observer differs')
    lower.write_text(text.replace(call,'#if !defined(DECOMP_PS2_NATIVE_VU) || defined(DECOMP_PS2_NATIVE_VU_PROGRAMS)\n'+call+'\n#endif'))
    # Guard the condition and call together, preserving VU0 register jumps.
    # Native programs use fixed arithmetic templates; reference builds retain
    # the pinned dynamic opcode entry points.
    for name in ('ps2_vu1_upper.cpp','ps2_vu1_lower.cpp'):
        path=folder/name;path.write_text('#ifndef DECOMP_PS2_NATIVE_VU\n'+path.read_text()+'\n#endif\n')
    path=folder/'ps2_vu1_program.cpp'
    path.write_text('#if !defined(DECOMP_PS2_NATIVE_VU) || defined(DECOMP_PS2_NATIVE_VU_PROGRAMS)\n'+path.read_text()+'\n#endif\n')
    vu_plain_sse.patch(root)
    vu_normalized_inputs.patch(root)


def generate(catalog,folder):
    folder=Path(folder);folder.mkdir(parents=True)
    words=sorted(catalog.words);declarations=[];entries=[]
    # Fixed arithmetic/memory operations share one hardware pipeline conductor.
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
    text=['#include "decomp_vu_catalog.hpp"',*declarations]
    if entries:
        # Every vector pair performs this lookup. A fixed, immutable table
        # avoids a binary search through the retail catalog on every pair.
        size=1
        while size<len(words)*2:size*=2
        table=[None]*size;maximum=0
        for word,entry in zip(words,entries):
            mixed=word^(word>>30);mixed=(mixed*0xbf58476d1ce4e5b9)&0xffffffffffffffff
            mixed^=mixed>>27;mixed=(mixed*0x94d049bb133111eb)&0xffffffffffffffff;mixed^=mixed>>31
            slot=mixed&(size-1);probes=1
            while table[slot] is not None:slot=(slot+1)&(size-1);probes+=1
            table[slot]=entry;maximum=max(maximum,probes)
        text.extend(['namespace {struct Entry{uint64_t word;DecompVuFunction unit0,unit1;};',
            'const Entry entries[]={',',\n'.join(e or '{0,nullptr,nullptr}' for e in table),'};}','''
DecompVuFunction decomp_find_vu_pair(uint64_t word,bool unit1){
    uint64_t mixed=word^(word>>30);mixed*=0xbf58476d1ce4e5b9ull;
    mixed^=mixed>>27;mixed*=0x94d049bb133111ebull;mixed^=mixed>>31;
    uint32_t slot=uint32_t(mixed)&'''+str(size-1)+'''u;
    for(unsigned n=0;n<'''+str(maximum)+'''u;++n){
        const auto &entry=entries[slot];
        if(!entry.unit0)return nullptr;
        if(entry.word==word)return unit1?entry.unit1:entry.unit0;
        slot=(slot+1)&'''+str(size-1)+'''u;
    }
    return nullptr;
}'''])
    else:text.append('DecompVuFunction decomp_find_vu_pair(uint64_t,bool){return nullptr;}')
    (folder/'catalog.cpp').write_text('\n'.join(text)+'\n')
    record=dict(pair_count=len(words),programs=catalog.records)
    (folder/'catalog.json').write_text(json.dumps(record,indent=2)+'\n')
    return record
