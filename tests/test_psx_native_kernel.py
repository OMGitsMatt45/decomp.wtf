"""CC0 original callback bridges checked against original-byte execution."""
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest


@pytest.fixture(scope='module')
def kernel_host(tmp_path_factory):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned BIOS bridge execution runs in the dedicated PS1 workflow')
    from decompnet.psx_native import _sdk,_run
    root=tmp_path_factory.mktemp('original kernel bridges');sdk=_sdk()
    (root/'bridge.inc').write_text(resources.files('decompnet.psx_native').joinpath('kernel_stubs.inc').read_text())
    (root/'runner.c').write_text(r'''
#include "cpu_state.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t words[4];
typedef struct {uint32_t lo,hi;} PsxKernelPatchRange;
void psx_check_interrupts_at(CPUState *cpu,uint32_t pc){(void)cpu;(void)pc;}
static uint32_t read_word(uint32_t address){return words[(address-0x9000u)/4u];}
#include "bridge.inc"
int main(int argc,char **argv){
    if(argc!=6)return 2;
    CPUState cpu={0};cpu.pc=(uint32_t)strtoul(argv[1],NULL,0);cpu.read_word=read_word;
    for(unsigned i=0;i<4;i++)words[i]=(uint32_t)strtoul(argv[i+2],NULL,0);
    for(unsigned i=1;i<32;i++)cpu.gpr[i]=i*0x01010101u;
    const PsxKernelPatchRange slots[]={{0x9000u,0x9010u},{0x9100u,0x9130u}};
    int handled=decomp_psx_kernel_stub(&cpu,cpu.pc,slots,2);
    printf("{\"handled\":%d,\"pc\":%u,\"dispatches\":%llu,\"registers\":[",handled,cpu.pc,
        (unsigned long long)decomp_kernel_stub_dispatches);
    for(unsigned i=0;i<32;i++)printf("%s%u",i?",":"",cpu.gpr[i]);puts("]}");return 0;
}''')
    quote=lambda p:json.dumps(p.as_posix())
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(OriginalBridges LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(bridge_probe runner.c)\n'
        'target_include_directories(bridge_probe PRIVATE '+quote(sdk/'runtime/include')+')\n')
    for command in (['cmake','-S',root,'-B',root/'build'],
                    ['cmake','--build',root/'build','--config','Release','--parallel','2']):
        _run(command,'Build original kernel bridge host')
    binary=next(p for p in (root/'build/bridge_probe',root/'build/bridge_probe.exe',
                            root/'build/Release/bridge_probe.exe') if p.exists())
    return binary


def words(reg,target,call):
    high=((target+0x8000)>>16)&0xffff
    return [(15<<26)|(reg<<16)|high,(9<<26)|(reg<<21)|(reg<<16)|(target&0xffff),
            (reg<<21)|((31<<11)|9 if call else 8),0]


def run(binary,address,body):
    done=subprocess.run([str(binary),hex(address),*map(hex,body)],capture_output=True,text=True,timeout=30)
    assert done.returncode==0,done.stdout+done.stderr
    return json.loads(done.stdout)


def test_declared_callback_bridges_match_registers_link_and_continuation(kernel_host):
    import unicorn
    from unicorn import mips_const as mips
    for reg in (2,8):
        for call in (False,True):
            for address in (0x9000,0x80009000,0xa0009000):
                for target in (0x0001f000,0x80018000,0xa001dfac):
                    body=words(reg,target,call);actual=run(kernel_host,address,body)
                    cpu=unicorn.Uc(unicorn.UC_ARCH_MIPS,unicorn.UC_MODE_MIPS32|unicorn.UC_MODE_LITTLE_ENDIAN)
                    cpu.mem_map(0,0x200000);cpu.mem_write(0x9000,struct.pack('<4I',*body))
                    for i in range(1,32):cpu.reg_write(mips.UC_MIPS_REG_0+i,i*0x01010101)
                    cpu.emu_start(address,target,count=4)
                    assert cpu.reg_read(mips.UC_MIPS_REG_PC)==target
                    assert actual['handled']==1 and actual['dispatches']==1 and actual['pc']==target
                    assert actual['registers']==[cpu.reg_read(mips.UC_MIPS_REG_0+i)&0xffffffff for i in range(32)]


def test_unlisted_slots_changed_instructions_and_unaligned_targets_are_unhandled(kernel_host):
    body=words(2,0x80018000,True)
    cases=[(0x9004,body),(0x9100,body),(0x30000,body),(0x9000,words(2,0x80018001,True))]
    for index in range(4):
        changed=list(body);changed[index]^=0x00200000 if index<3 else 1
        cases.append((0x9000,changed))
    for address,candidate in cases:
        actual=run(kernel_host,address,candidate)
        assert actual==dict(handled=0,pc=address,dispatches=0,
                            registers=[0]+[i*0x01010101 for i in range(1,32)])
