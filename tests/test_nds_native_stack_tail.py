"""Original stack-driven PC transfers; no game or SDK instruction payloads."""
import json
import struct
import subprocess

import pytest

from decompnet import nds_native
from .test_nds_native import sdk, hardware_project  # noqa: F401


@pytest.mark.parametrize('destination', ['arm', 'thumb', 'incoming_lr'])
def test_shared_arm_stack_pc_tail_and_real_return(tmp_path, sdk, hardware_project, destination):
    base = 0x0201e000
    raw = bytearray(0x100)
    # Thumb caller owns its saved LR and a 256-byte frame, then crosses a
    # BX-PC veneer into ARM. An external tail must return to that caller.
    struct.pack_into('<8H', raw, 0, 0xb510, 0xb0be, 0x245a, 0xf000,
                     0xf80b, 0x3001, 0xb03e, 0xbd10)
    struct.pack_into('<2H', raw, 0x20, 0x4778, 0x46c0)
    if destination == 'incoming_lr':
        # MOV r0,#41; PUSH {lr}; POP {pc}: a genuine return, not a tail.
        struct.pack_into('<3I', raw, 0x24, 0xe3a00029, 0xe92d4000, 0xe8bd8000)
    else:
        # LDR ip,literal; PUSH {ip}; POP {pc}. No saved incoming LR occupies
        # this slot: the restored PC is an external computed tail target.
        struct.pack_into('<4I', raw, 0x24, 0xe59fc004, 0xe92d1000,
                         0xe8bd8000, base+0x80+(destination == 'thumb'))
    thumb = destination == 'thumb'
    if thumb:
        struct.pack_into('<2H', raw, 0x80, 0x2029, 0x4770)
    else:
        struct.pack_into('<2I', raw, 0x80, 0xe3a00029, 0xe12fff1e)
    image = tmp_path/'original.bin'
    image.write_bytes(raw)
    module = dict(name='original', module_id=3, base=base, image=str(image),
        functions=[dict(addr=base, size=16, thumb=True, name='caller'),
                   dict(addr=base+0x20, size=2, thumb=True, name='veneer'),
                   dict(addr=base+0x24, size=12, thumb=False, name='stack_transfer'),
                   dict(addr=base+0x80, size=4 if thumb else 8, thumb=thumb, name='external_leaf')],
        labels=[], calls=[], code_ranges=[[base,base+16],[base+0x20,base+0x22],
            [base+0x24,base+0x30],[base+0x80,base+0x88]],
        data_ranges=[[base+16,base+0x20],[base+0x22,base+0x24],
            [base+0x30,base+0x80],[base+0x88,base+0x100]],
        dispatch_regions=[dict(addr=base+0x24, size=16, thumb=False,
            entries=[base+0x24], data_ranges=[[base+0x30,base+0x34]])])
    _, emitter, _ = nds_native._sdk()
    report = emitter.emit_manifest(dict(cpu='arm9',arch='v5te',modules=[module]),tmp_path/'generated')
    assert report['undefined_sites'] == 0
    _, project, _ = hardware_project
    runtime = project/'native/dsr/runtime'
    libraries = list((project/'build').rglob('libds_runtime.a'))+list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries) == 1
    (tmp_path/'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include "decls.h"
#include <fstream>
#include <vector>
int main(int argc,char** argv) {
 dsr::MachineConfig config;config.direct_boot=false;config.arm9_table=dsr::gen_table_arm9();
 dsr::Machine machine(config);auto& c=machine.cpu(dsr::CpuId::Arm9);
 std::ifstream file(argv[1],std::ios::binary);
 std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
 for(unsigned i=0;i<bytes.size();++i)machine.write8(dsr::CpuId::Arm9,0x0201e000+i,bytes[i]);
 c.budget=10000;c.r[0]=0;
 for(unsigned i=4;i<12;++i)c.r[i]=0xcafe0000+i;
 c.r[13]=0x02030000;c.r[14]=0x02001001;
 dsr::dsr_call(&c,0x0201e001);
 if(c.r[0]!=42||c.r[13]!=0x02030000||!(dsr::dsr_mrs_cpsr(&c)&0x20))return 1;
 for(unsigned i=4;i<12;++i)if(c.r[i]!=0xcafe0000+i)return 2;
 for(unsigned i=0;i<bytes.size();++i)
  if(machine.read8(dsr::CpuId::Arm9,0x0201e000+i)!=bytes[i])return 3;
 return 0;
}
''')
    quote = lambda p: json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(StackTailChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\n'
        'file(GLOB GENERATED generated/*.cpp)\nadd_executable(stack_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(stack_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(stack_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(stack_checks PRIVATE bcrypt)\nendif()\n')
    build = tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done = subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert done.returncode == 0,done.stdout+done.stderr
    executable = next(p for p in (build/'stack_checks',build/'Release/stack_checks.exe')if p.exists())
    done = subprocess.run([str(executable),str(image)],capture_output=True,text=True,timeout=15)
    assert done.returncode == 0,done.stdout+done.stderr
    assert image.read_bytes() == raw
