// SPDX-License-Identifier: CC0-1.0

#include "lle/iop.h"
#include "decomp_iop_execution.hpp"
#include <array>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>
using namespace ps2x::iop::lle;
struct Link:EeLink {
    bool readEe(uint32_t,void*,uint32_t)override{return false;}
    bool writeEe(uint32_t,const void*,uint32_t)override{return false;}
    bool eeServer(uint32_t)override{return false;}
    void log(const std::string &message)override{std::fprintf(stderr,"%s\n",message.c_str());}
};
struct Device:IoDevice {
    uint32_t ioRead(uint32_t,unsigned)override{return 0;}
    void ioWrite(uint32_t,uint32_t,unsigned)override{}
};
void print(const CpuContext &c,StopReason reason,uint64_t cycles,Cpu &cpu){
    std::printf("%u %u %u %u %u %llu ",unsigned(reason),c.pc,c.branchTarget,unsigned(c.branchPending),
        unsigned(c.loadRegister),(unsigned long long)cycles);
    for(auto word:c.gpr)std::printf("%u ",word);
    std::printf("%u %u\n",cpu.syscallCode(),cpu.faultPc());
}
int main(int argc,char **argv){
    if(argc!=2)return 1;std::ifstream in(argv[1],std::ios::binary);
    std::vector<uint8_t> file((std::istreambuf_iterator<char>(in)),{});
    Link link;auto iop=std::make_unique<Iop>(link);
    const auto id=iop->loadModule(file,"test.irx",{"one","two"});
    std::array<uint32_t,2> observed{};iop->readMemory(0x1f0000,observed.data(),8);
    if(id<=0||observed[0]!=3||observed[1]!='t')return 2;
    std::printf("%d %u %u\n",id,observed[0],observed[1]);
    for(uint32_t base:{0x10000u,0x40000u})for(uint32_t segment:{0u,0x80000000u,0xa0000000u}){
        Device device;Bus bus(device);Cpu cpu(bus);IrxImage image;std::string error;std::vector<IrxImport> imports;
        if(!parseIrx(file,image,error)||!relocateIrx(image,bus.ram(),Bus::kRamBytes,base,imports,error)||!cpu.nativeBind(image,base))return 3;
        bus.write32(0x1000,0x4c);cpu.nativeKernelCall(0x1000,0x4c,1);
        bus.write32(0x1e0000,0x1e1000);bus.write8(0x1e1000,'r');
        CpuContext c;c.pc=segment+base;c.gpr[4]=7;c.gpr[5]=0x1e0000;c.gpr[31]=segment+0x1000;
        uint64_t cycles=0;const auto reason=cpu.run(c,cycles,1000);
        if(reason!=StopReason::Syscall||bus.read32(0x1f0000)!=7||bus.read32(0x1f0004)!='r'||bus.read32(base+40)!=base+4)return 4;
        print(c,reason,cycles,cpu);
    }
    // Original kernel-generated import jumps and traps retain delay state.
    for(unsigned seed=0;seed<32;++seed)for(bool call:{false,true}){
        Device device;Bus bus(device);Cpu cpu(bus);CpuContext c;
        const uint32_t word=call?0x14cu:0x08010000u;
        bus.write32(0x1200,word);
        if(call)cpu.nativeKernelCall(0x1200,word,5);else cpu.nativeKernelJump(0x1200,word,0x40000);
        c.pc=0xa0001200;c.branchPending=seed&1;c.branchTarget=0x80013000;
        c.loadRegister=uint8_t(seed);c.loadValue=0x12345678;c.gpr[31]=0x80018000;
        uint64_t cycles=0;const auto reason=cpu.run(c,cycles,1);print(c,reason,cycles,cpu);
    }
#ifdef DECOMP_PS2_NATIVE_IOP
    {
        Device device;Bus bus(device);Cpu cpu(bus);IrxImage image;std::string error;std::vector<IrxImport> imports;
        if(!parseIrx(file,image,error)||!relocateIrx(image,bus.ram(),Bus::kRamBytes,0x10000,imports,error)||!cpu.nativeBind(image,0x10000))return 5;
        bus.write32(0x10000,bus.read32(0x10000)^1u);CpuContext c;c.pc=0x80010000;uint64_t cycles=0;
        if(cpu.run(c,cycles,10)!=StopReason::Fault||cycles||cpu.faultPc()!=0x80010000)return 6;
        image.image[0]^=1;if(cpu.nativeBind(image,0x10000))return 7;
        const auto &execution=decomp_ps2::execution::iop_interpreted_instructions;
        if(execution.load()!=0||!decomp_ps2::execution::iop_native_instructions.load()||
           decomp_ps2::execution::iop_coverage_misses.load()!=2)return 8;
    }
#endif
}
