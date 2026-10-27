// SPDX-License-Identifier: GPL-3.0-only
// Native dispatch conductor; instruction semantics are selected during export.
#include "decomp_iop_catalog.hpp"
#include "decomp_iop_execution.hpp"
#include <algorithm>
#include <cstdio>
#include <cstring>

namespace ps2x::iop::lle {
namespace {
bool same(const IrxImage &image,const DecompNativeModule &module) {
    if(image.image.size()!=module.size||image.textSize!=module.text||
       image.entry!=module.entry||image.gp!=module.gp||image.bssSize!=module.bss||
       image.relocations.size()!=module.relocationCount||
       std::memcmp(image.image.data(),module.image,module.size))return false;
    for(size_t n=0;n<module.relocationCount;++n)
        if(image.relocations[n].offset!=module.relocations[n].offset||
           image.relocations[n].type!=module.relocations[n].type)return false;
    return true;
}
}

bool Cpu::nativeBind(const IrxImage &image,uint32_t base) {
    size_t count=0;const auto *modules=decomp_iop_catalog(count);
    const DecompNativeModule *module=nullptr;
    for(size_t n=0;n<count;++n)if(same(image,modules[n])){module=modules+n;break;}
    if(!module||(base&3u)||base>Bus::kRamBytes||module->size>Bus::kRamBytes-base){
        decomp_ps2::execution::iop_gap(base+image.entry);return false;
    }
    if(m_nativeCode.empty())m_nativeCode.resize(Bus::kRamBytes/4);
    // Validate relocation invariants before publishing any instruction entries.
    for(uint32_t offset=0;offset+4<=module->text;offset+=4){
        const auto &instruction=module->instructions[offset/4];
        if(!instruction.function)continue;
        const uint32_t expected=m_bus.fetch(base+offset);
        if((expected&~instruction.mask)!=(instruction.word&~instruction.mask)){
            decomp_ps2::execution::iop_gap(base+offset);return false;
        }
    }
    for(uint32_t offset=0;offset+4<=module->text;offset+=4){
        const auto &instruction=module->instructions[offset/4];
        const uint32_t expected=m_bus.fetch(base+offset);
        m_nativeCode[(base+offset)/4]={expected,expected,instruction.function};
    }
    return true;
}

void Cpu::nativeKernelCall(uint32_t address,uint32_t expected,uint32_t code) {
    if(m_nativeCode.empty())m_nativeCode.resize(Bus::kRamBytes/4);
    if((address&3u)||address>Bus::kRamBytes-4){decomp_ps2::execution::iop_gap(address);return;}
    m_nativeCode[address/4]={expected,code,
        +[](Cpu &cpu,CpuContext &c,uint64_t &cycles,uint32_t value){return cpu.nativeTrap(c,cycles,value);}};
}
void Cpu::nativeKernelJump(uint32_t address,uint32_t expected,uint32_t target) {
    if(m_nativeCode.empty())m_nativeCode.resize(Bus::kRamBytes/4);
    if((address&3u)||address>Bus::kRamBytes-4){decomp_ps2::execution::iop_gap(address);return;}
    m_nativeCode[address/4]={expected,target,
        +[](Cpu &cpu,CpuContext &c,uint64_t &cycles,uint32_t value){return cpu.nativeJump(c,cycles,value);}};
}

StopReason Cpu::nativeTrap(CpuContext &c,uint64_t &cycles,uint32_t code) {
    ++cycles;m_syscallCode=code;
    c.pc=c.branchPending?c.branchTarget:c.pc+4u;c.branchPending=false;
    if(c.loadRegister)c.gpr[c.loadRegister]=c.loadValue;
    c.loadRegister=0;return StopReason::Syscall;
}
StopReason Cpu::nativeJump(CpuContext &c,uint64_t &cycles,uint32_t target) {
    ++cycles;
    const uint32_t next=c.branchPending?c.branchTarget:c.pc+4u;
    c.branchTarget=(c.pc&0xf0000000u)|(target&0x0fffffffu);c.branchPending=true;
    if(c.loadRegister)c.gpr[c.loadRegister]=c.loadValue;
    c.loadRegister=0;c.gpr[0]=0;c.pc=next;return StopReason::Budget;
}

StopReason Cpu::run(CpuContext &context,uint64_t &cycles,uint64_t budget) {
    uint64_t instructions=0;
    struct Accounting {
        uint64_t &instructions;
        ~Accounting(){decomp_ps2::execution::iop_native_instructions.fetch_add(instructions,std::memory_order_relaxed);}
    } accounting{instructions};
    while(cycles<budget){
        const uint32_t pc=context.pc,physical=pc&0x1fffffffu;
        const NativeEntry *entry=nullptr;
        if(!(pc&3u)&&physical<0x800000u&&!m_nativeCode.empty())
            entry=&m_nativeCode[(physical&(Bus::kRamBytes-1))/4];
        if(!entry||!entry->function||m_bus.fetch(pc)!=entry->expected){
            m_faultPc=pc;decomp_ps2::execution::iop_gap(pc);
            std::fprintf(stderr,"decomp.wtf: missing native IOP code at %08x\n",pc);
            return StopReason::Fault;
        }
        ++instructions;
        const StopReason result=entry->function(*this,context,cycles,entry->operand);
        if(result==StopReason::Fault)decomp_ps2::execution::iop_gap(pc);
        if(result!=StopReason::Budget)return result;
    }
    return StopReason::Budget;
}
}
