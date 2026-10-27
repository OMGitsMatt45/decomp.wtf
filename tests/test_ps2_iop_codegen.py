"""Original operand probes compare fixed native IOP operations with the pin."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.ps2_native.iop_codegen import Semantics


def sdk_source():
    root=os.environ.get('DECOMP_PS2_IOP_REFERENCE')
    if not root and os.environ.get('DECOMP_PS2_PORT_SDK'):
        root=str(Path(os.environ['DECOMP_PS2_PORT_SDK'])/'thirdparty/PS2Recomp/ps2xIOP/src/lle')
    if not root:pytest.skip('pinned IOP source path is required for native CPU qualification')
    return Path(root)


def words():
    rs,rt,rd=3,4,5
    primary=[(op<<26)|(rs<<21)|(rt<<16)|21 for op in
        [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,32,33,34,35,36,37,38,40,41,42,43,46,47,51,63]]
    special=[(rs<<21)|(rt<<16)|(rd<<11)|(7<<6)|op for op in
        [0,2,3,4,6,7,8,9,12,13,16,17,18,19,24,25,26,27,32,33,34,35,36,37,38,39,42,43,63]]
    return sorted(set([0,*primary,*special,
        *[(1<<26)|(rs<<21)|(kind<<16)|0xfffd for kind in (0,1,16,17)],
        (16<<26)|(rt<<16)|(12<<11),
        (16<<26)|(4<<21)|(rt<<16)|(12<<11),0x42000010]))


def test_native_operations_preserve_pinned_iop_context_and_memory(tmp_path):
    source=sdk_source();compiler=shutil.which('c++')
    if not compiler:pytest.skip('native C++ compiler required')
    semantics=Semantics((source/'cpu.cpp').read_text())
    header=(source/'cpu.h').read_text()
    marker='        uint32_t syscallCode() const noexcept'
    assert header.count(marker)==1
    header=header.replace(marker,'        template <uint32_t Word,uint32_t Mask>\n'
        '        StopReason nativeStep(CpuContext&,uint64_t&,uint32_t);\n'+marker)
    (tmp_path/'cpu.h').write_text(header);shutil.copyfile(source/'bus.h',tmp_path/'bus.h')
    operations=words()
    bodies='\n'.join(semantics.emit(word) for word in operations)
    assert 'switch (' not in bodies and 'm_bus.fetch' not in bodies
    (tmp_path/'native.cpp').write_text('#include "cpu.h"\n#include "bus.h"\n'
        'namespace ps2x::iop::lle {\n'+bodies+'}\n')
    runner=r'''
#include "cpu.h"
#include "bus.h"
#include <cstdio>
#include <cstring>
using namespace ps2x::iop::lle;
struct Device:IoDevice{
    uint32_t trace=0;
    uint32_t ioRead(uint32_t p,unsigned n)override{trace=trace*31u+p+n;return trace;}
    void ioWrite(uint32_t p,uint32_t v,unsigned n)override{trace=trace*31u+p+v+n;}
};
int main(){
    const uint32_t words[]={WORDS};
    using Function=StopReason(*)(Cpu&,CpuContext&,uint64_t&,uint32_t);
#ifdef NATIVE
    const Function functions[]={FUNCTIONS};
#endif
    for(unsigned index=0;index<sizeof(words)/sizeof(words[0]);++index){
      for(unsigned seed=0;seed<32;++seed){
        Device device;Bus bus(device);Cpu cpu(bus);CpuContext state;
        for(unsigned r=1;r<32;++r)state.gpr[r]=(0x9e3779b9u*(r+seed))^(seed<<28u);
        state.gpr[3]=seed%4==0?0x1f801000u:0x400u+(seed&3u);
        if(seed%5==0)state.gpr[4]=0;
        if(seed%7==0)state.gpr[3]=0x80000000u;
        state.pc=0x80010000u;state.hi=seed*3;state.lo=seed*7;
        state.branchPending=(seed&1u)!=0;state.branchTarget=0xa0018000u;
        state.loadRegister=uint8_t(seed%32);state.loadValue=0x12345678u+seed;
        for(unsigned byte=0;byte<Bus::kRamBytes;++byte)bus.ram()[byte]=uint8_t(byte+seed);
        bus.write32(state.pc,words[index]);cpu.setCop0Status(0x76543210u+seed);
        uint64_t cycles=123;StopReason result;
#ifdef NATIVE
        result=functions[index](cpu,state,cycles,words[index]);
#else
        result=cpu.run(state,cycles,124);
#endif
        uint32_t digest=0;for(unsigned byte=0;byte<Bus::kRamBytes;++byte)digest=(digest*33u)^bus.ram()[byte];
        std::printf("%u %u %u %u %u %u %u %u %u %u %u %llu %u %u ",unsigned(result),
          state.pc,state.hi,state.lo,state.branchTarget,unsigned(state.branchPending),
          unsigned(state.loadRegister),state.loadValue,cpu.syscallCode(),cpu.faultPc(),cpu.cop0Status(),
          (unsigned long long)cycles,digest,device.trace);
        for(auto r:state.gpr)std::printf("%u ",r);std::puts("");
      }
    }
}
'''
    runner=runner.replace('WORDS',','.join(hex(word)+'u' for word in operations))
    runner=runner.replace('FUNCTIONS',','.join(
        '+[](Cpu& cpu,CpuContext& c,uint64_t& cycles,uint32_t value){return cpu.nativeStep<'+
        hex(word)+'u,0u>(c,cycles,value);}' for word in operations))
    (tmp_path/'runner.cpp').write_text(runner)
    for name,extra in (('reference',[str(source/'cpu.cpp')]),('native',['-DNATIVE',str(tmp_path/'native.cpp')])):
        binary=tmp_path/(name+('.exe' if os.name=='nt' else ''))
        done=subprocess.run([compiler,'-std=c++17','-O1','-I',str(tmp_path),str(tmp_path/'runner.cpp'),*extra,'-o',str(binary)],
            capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
        result=subprocess.run([str(binary)],capture_output=True,check=True,timeout=90)
        (tmp_path/(name+'.txt')).write_bytes(result.stdout)
    assert (tmp_path/'native.txt').read_bytes()==(tmp_path/'reference.txt').read_bytes()


def test_relocation_operands_cannot_select_an_instruction():
    semantics=Semantics((sdk_source()/'cpu.cpp').read_text())
    assert 'relocated&0x0000ffffu' in semantics.emit(0x3c048000,0xffff)
    assert 'relocated&0x03ffffffu' in semantics.emit(0x0c000400,0x3ffffff)
    for word,mask in ((0x00851021,0xffff),(0x42000010,0xffff),(0x3c048000,0x3ffffff)):
        with pytest.raises(ValueError,match='instruction selection'):semantics.emit(word,mask)
