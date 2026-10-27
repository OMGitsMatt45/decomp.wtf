"""Original IRX loading, relocation, kernel bridges and native byte guards."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet import pc
from decompnet.ps2_native import iop_native
from .fixtures.ps2_iop import original_irx
from .test_ps2_iop_codegen import sdk_source


def test_irx_input_parser_rejects_changed_headers_and_relocations():
    original=original_irx();module=iop_native.parse(original)
    assert module['text']==40 and module['bss']==16 and module['relocations']==[(40,2)]
    for offset,value in ((4,2),(5,2),(0x12,62),(0x84,0xff),(0x144,0xff)):
        changed=bytearray(original);changed[offset]=value
        with pytest.raises(pc.PCError):iop_native.parse(bytes(changed))
    assert original==original_irx()


def test_native_irx_and_kernel_execution_matches_reference_and_rejects_changed_code(tmp_path):
    source=sdk_source();compiler=shutil.which('c++')
    if not compiler:pytest.skip('native C++ compiler required')
    root=tmp_path/'runtime';lle=root/'thirdparty/PS2Recomp/ps2xIOP/src/lle'
    shutil.copytree(source,lle);iop_native.patch(root)
    generated=tmp_path/'native';record=iop_native.generate([('ORIGINAL.IRX',original_irx())],source/'cpu.cpp',generated)
    assert record['native_operations']==8 and len(record['modules'])==1
    resources=Path(iop_native.__file__).parent
    for name,target in (('iop_catalog.hpp','decomp_iop_catalog.hpp'),('iop_execution.hpp','decomp_iop_execution.hpp'),
                         ('iop_engine.cpp','engine.cpp')):
        shutil.copyfile(resources/name,generated/target)
    original=tmp_path/'original.irx';original.write_bytes(original_irx())
    runner=r'''
#include "lle/iop.h"
#include "decomp_iop_execution.hpp"
#include <array>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <memory>
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
#ifdef NATIVE
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
'''
    (tmp_path/'runner.cpp').write_text(runner)
    common=[str(lle/(name+'.cpp')) for name in ('irx','iop','kernel','spu2')]
    for name,extra in (('reference',[str(lle/'cpu.cpp')]),
                        ('native',['-DNATIVE',*map(str,generated.glob('*.cpp'))])):
        binary=tmp_path/(name+'_probe'+('.exe' if os.name=='nt' else ''))
        result=subprocess.run([compiler,'-std=c++20','-O1','-I',str(lle.parent),'-I',str(lle),'-I',str(generated),
            str(tmp_path/'runner.cpp'),*common,*extra,'-o',str(binary)],capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stdout+result.stderr
        done=subprocess.run([str(binary),str(original)],capture_output=True,timeout=30)
        assert done.returncode==0,done.stderr.decode()
        (tmp_path/(name+'.txt')).write_bytes(done.stdout)
    assert (tmp_path/'reference.txt').read_bytes()==(tmp_path/'native.txt').read_bytes()
