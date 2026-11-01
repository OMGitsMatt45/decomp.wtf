"""Original Thumb long branches with guarded dispatch and a shared frame."""
import json
import struct
import subprocess

import pytest
from decompnet import nds_native
from .test_nds_native import sdk, hardware_project  # noqa: F401


def program(tmp_path, mutation=None):
    base=0x02014000;raw=bytearray(0x220)
    def halves(offset,*values):struct.pack_into('<'+'H'*len(values),raw,offset,*values)
    def branch(site,target):halves(site,0xe000|(((target-site-4)//2)&0x7ff))
    def call(site,target):
        delta=target-site-4
        halves(site,0xf000|((delta>>12)&0x7ff),0xf800|((delta>>1)&0x7ff))
    halves(0,0xb510,0xb081,0x245a,0x2800,0xd01a)
    call(0xa,0x40);halves(0xe,0xde00)  # unreachable only for a proven long branch
    halves(0x40,0x2802,0xd80e,0x0041,0x4479,0x88c9,0x0409,0x1409,0x448f,
           4,8,12,0x200a)
    branch(0x58,0x80);halves(0x5a,0x200b);branch(0x5c,0x80)
    halves(0x5e,0x200c);branch(0x60,0x80);halves(0x62,0x200d);branch(0x64,0x80)
    halves(0x80,0x2203,0x3001,0x3a01,0xd1fc,*([0x46c0]*16))
    call(0xa8,0x200);halves(0xac,0xb001,0xbd10)
    # An ordinary internal callee owns a separate frame and must resume BL+4.
    halves(0x180,0xb510,0xb081);call(0x184,0x1c0);halves(0x188,0x3004,0xb001,0xbd10)
    halves(0x1c0,0xb500,0x3001,0xbd00);halves(0x200,0xb500,0x3001,0xbd00)
    mode=mutation or ''
    if 'long_loop' in mode:
        # The compiler can use BL to reach a loop test which branches back
        # into this same frame. It is not a returning internal subroutine.
        call(0x86,0xa0);halves(0x8a,0x20ee);branch(0x8c,0xac)
        halves(0xa0,0x2a00,0xd1ee,0x46c0,0x46c0)
    if 'inplace' in mode:
        halves(0x44,0x0040,0x4478,0x88c0,0x0400,0x1400,0x4487)
    if 'taken' in mode:
        setup=bytes(raw[0x44:0x50]);raw[0x48:0x54]=setup
        halves(0x42,0xd901);call(0x44,0x66)
        halves(0x54,4,8,12,0x200a);branch(0x5c,0x80)
        halves(0x5e,0x200b);branch(0x60,0x80)
        halves(0x62,0x200c);branch(0x64,0x80)
        halves(0x66,0x200d);branch(0x68,0x80)
    if mode=='taken_inplace_bypass':branch(0x5c,0x4c)
    if mode=='inplace_clobber':halves(0x4a,0x43c0)
    if mutation=='unguarded':halves(0x40,0x46c0,0x46c0)
    if mutation=='guard_bypass':branch(0x58,0x44)
    if mutation=='wrong_release':halves(0xac,0xb002)
    image=tmp_path/'original-thumb.bin';image.write_bytes(raw)
    functions=[dict(addr=base+offset,size=size,thumb=True,name=f'original_{offset:x}')
               for offset,size in ((0,0x180),(0x180,0x60),(0x1c0,6),(0x200,6))]
    manifest=dict(cpu='arm9',arch='v5te',modules=[dict(name='arm9main',module_id=-1,
        base=base,image=str(image),functions=functions,labels=[],calls=[],
        code_ranges=[[base,base+len(raw)]],data_ranges=[[base+0x54,base+0x5a] if 'taken' in mode else [base+0x50,base+0x56]])])
    return manifest


@pytest.mark.parametrize('mutation',['unguarded','guard_bypass','wrong_release','taken_inplace_bypass','inplace_clobber'])
def test_unproven_body_does_not_hide_fallthrough(tmp_path,sdk,mutation):
    manifest=program(tmp_path,mutation);_,emitter,_=nds_native._sdk()
    output=tmp_path/'generated';output.mkdir()
    # The invalid fallthrough remains observable when the proof fails.
    assert emitter.emit_manifest(manifest,output)['undefined_sites']>0


def test_long_loop_condition_has_no_returning_fallthrough(tmp_path,sdk):
    manifest=program(tmp_path,'long_loop');_,emitter,_=nds_native._sdk()
    output=tmp_path/'generated';output.mkdir()
    assert emitter.emit_manifest(manifest,output)['undefined_sites']==0


@pytest.mark.parametrize('mutation',[None,'long_loop','inplace','taken_inplace','long_loop_taken_inplace'])
def test_long_body_branch_and_ordinary_call_execute_with_balanced_frames(tmp_path,sdk,hardware_project,mutation):
    manifest=program(tmp_path,mutation);_,emitter,_=nds_native._sdk()
    output=tmp_path/'generated';output.mkdir()
    result=emitter.emit_manifest(manifest,output)
    assert result['undefined_sites']==0
    _,project,_=hardware_project;runtime=project/'native/dsr/runtime'
    libraries=list((project/'build').rglob('libds_runtime.a'))+list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries)==1
    (tmp_path/'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include "decls.h"
#include <fstream>
#include <vector>
int main(int argc,char** argv) {
 dsr::MachineConfig config;config.direct_boot=false;config.arm9_table=dsr::gen_table_arm9();
 dsr::Machine machine(config);auto& cpu=machine.cpu(dsr::CpuId::Arm9);
 std::ifstream file(argv[1],std::ios::binary);
 std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
 for(unsigned i=0;i<bytes.size();++i)machine.write8(dsr::CpuId::Arm9,0x02014000+i,bytes[i]);
 for(unsigned value=0;value<4;++value) {
  cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;cpu.r[4]=0x55aa;
  cpu.r[0]=value;dsr::dsr_call(&cpu,0x02014001);
  if(cpu.r[0]!=14+value || cpu.r[4]!=0x55aa || cpu.r[13]!=0x023ff000)return 1;
 }
 cpu.r[0]=5;cpu.r[14]=0x02015000;dsr::dsr_call(&cpu,0x02014181);
 return cpu.r[0]==10 && cpu.r[4]==0x55aa && cpu.r[13]==0x023ff000 ? 0 : 2;
}
''')
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(BodyTailChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        'find_package(Threads REQUIRED)\nfile(GLOB GENERATED generated/*.cpp)\n'
        'add_executable(body_tail_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(body_tail_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(body_tail_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(body_tail_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode==0,run.stdout+run.stderr
    executable=next(p for p in (build/'body_tail_checks',build/'Release/body_tail_checks.exe') if p.exists())
    run=subprocess.run([str(executable),manifest['modules'][0]['image']],capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr
