"""A direct ARM7 callee omitted from the input manifest must still execute."""
import json
import struct
import subprocess
import pytest

from decompnet import nds_native
from decompnet.nds_native.callbacks import recover
from .test_nds_native import sdk, hardware_project  # noqa: F401


def arm_halfword_image(tmp_path,gap=False):
    base=0x03800000;raw=bytearray(0x78)
    struct.pack_into('<7I',raw,0,0xE92D40F0,0xE3A0405A,0xE3500002,0x8A000017,
                     0xE08F0080,0xE1D000B4,0xE08FF000)
    struct.pack_into('<3H',raw,0x1c,0x20,0x30,0x40)
    raw[0x24:0x40]=struct.pack('<I',0xE7F000F0)*7
    for offset,value in [(0x40,11),(0x50,22),(0x60,33),(0x70,99)]:
        struct.pack_into('<2I',raw,offset,0xE3A00000|value,0xE8BD80F0)
    if gap:
        raw[0xc:0xc]=struct.pack('<3I',0xE3A05001,0xE3A06002,0xE3A07003)
    image=tmp_path/'original-arm-halfword.bin';image.write_bytes(raw)
    return dict(cpu='arm7',arch='v4t',modules=[dict(name='original',module_id=-5,base=base,image=str(image),
        functions=[dict(addr=base,size=len(raw),thumb=False,name='entry')],labels=[],calls=[],
        code_ranges=[[base,base+len(raw)]],data_ranges=[])]),image


@pytest.mark.parametrize('gap',[False,True])
def test_arm7_guarded_halfword_table_does_not_decode_offset_words_as_code(tmp_path,sdk,gap):
    manifest,_=arm_halfword_image(tmp_path,gap)
    _,emitter,_=nds_native._sdk()
    result=emitter.emit_manifest(manifest,tmp_path/'generated')
    assert result['undefined_sites']==0
    assert result['jump_tables']>0


@pytest.mark.parametrize('gap',[False,True])
def test_arm7_halfword_dispatch_executes_cases_and_default_with_saved_frame(tmp_path,sdk,hardware_project,gap):
    manifest,image=arm_halfword_image(tmp_path,gap)
    _,emitter,_=nds_native._sdk()
    assert emitter.emit_manifest(manifest,tmp_path/'generated')['undefined_sites']==0
    _,project,_=hardware_project
    runtime=project/'native/dsr/runtime'
    libraries=list((project/'build').rglob('libds_runtime.a'))+list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries)==1
    (tmp_path/'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include "decls.h"
#include <fstream>
#include <vector>
int main(int argc,char** argv) {
 dsr::MachineConfig config;config.direct_boot=false;config.arm7_table=dsr::gen_table_arm7();
 dsr::Machine machine(config);auto& cpu=machine.cpu(dsr::CpuId::Arm7);
 std::ifstream file(argv[1],std::ios::binary);
 std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
 for(unsigned i=0;i<bytes.size();++i)machine.write8(dsr::CpuId::Arm7,0x03800000+i,bytes[i]);
 unsigned keys[]={0,1,2,3,0xffffffffu},expected[]={11,22,33,99,99};
 for(unsigned i=0;i<5;++i) {
  cpu.budget=10000;cpu.r[0]=keys[i];cpu.r[4]=0xcafe;cpu.r[13]=0x0380ff00;cpu.r[14]=0x02000000;
  dsr::dsr_call(&cpu,0x03800000);
  if(cpu.r[0]!=expected[i]||cpu.r[4]!=0xcafe||cpu.r[13]!=0x0380ff00)return 1;
 }
 for(unsigned i=0;i<bytes.size();++i)if(machine.read8(dsr::CpuId::Arm7,0x03800000+i)!=bytes[i])return 2;
 return 0;
}
''')
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(ArmHalfwordChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\n'
        'file(GLOB GENERATED generated/*.cpp)\nadd_executable(arm_table_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(arm_table_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(arm_table_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(arm_table_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    executable=next(p for p in (build/'arm_table_checks',build/'Release/arm_table_checks.exe')if p.exists())
    done=subprocess.run([str(executable),str(image)],capture_output=True,text=True,timeout=15)
    assert done.returncode==0,done.stdout+done.stderr


def test_arm7_direct_call_recovers_unclassified_leaf(tmp_path, sdk, hardware_project):
    base = 0x03800000
    raw = bytearray(0x40)
    struct.pack_into('<3I', raw, 0, 0xe92d4000, 0xeb000009, 0xe8bd8000)
    struct.pack_into('<2I', raw, 0x30, 0xe3a00029, 0xe12fff1e)
    image = tmp_path / 'original-arm7.bin'
    image.write_bytes(raw)
    manifest = dict(cpu='arm7', arch='v4t', modules=[dict(
        name='original_private_wram', module_id=-5, base=base, image=str(image),
        functions=[dict(addr=base, size=12, thumb=False, name='entry')],
        labels=[], calls=[], code_ranges=[[base, base+12]],
        data_ranges=[[base+0x38, base+0x3c]])])
    _, emitter, reader = nds_native._sdk()
    added = recover(manifest, emitter, reader)
    assert len(added) == 1
    assert added[0]['address'] == base+0x30
    assert added[0]['pointer_sources'] == []
    assert added[0]['call_sources'] == [dict(module_id=-5, address=base+4)]
    assert recover(manifest, emitter, reader) == []
    generated = tmp_path / 'generated'
    generated.mkdir()
    assert emitter.emit_manifest(manifest, generated)['undefined_sites'] == 0
    _, project, _ = hardware_project
    runtime = project / 'native/dsr/runtime'
    libraries = list((project/'build').rglob('libds_runtime.a')) + list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries) == 1
    (tmp_path/'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include "decls.h"
#include <fstream>
#include <vector>
int main(int argc,char** argv) {
 dsr::MachineConfig config;config.direct_boot=false;config.arm7_table=dsr::gen_table_arm7();
 dsr::Machine machine(config);auto& cpu=machine.cpu(dsr::CpuId::Arm7);
 std::ifstream file(argv[1],std::ios::binary);
 std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
 for(unsigned i=0;i<bytes.size();++i)machine.write8(dsr::CpuId::Arm7,0x03800000+i,bytes[i]);
 cpu.budget=10000;cpu.r[13]=0x0380ff00;cpu.r[14]=0x02000000;
 dsr::dsr_call(&cpu,0x03800000);
 return cpu.r[0]==41 && cpu.r[13]==0x0380ff00 ? 0 : 1;
}
''')
    quote = lambda p: json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(Arm7CalleeChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        'find_package(Threads REQUIRED)\nfile(GLOB GENERATED generated/*.cpp)\n'
        'add_executable(arm7_callee_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(arm7_callee_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(arm7_callee_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(arm7_callee_checks PRIVATE bcrypt)\nendif()\n')
    build = tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run = subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode == 0, run.stdout+run.stderr
    executable = next(p for p in (build/'arm7_callee_checks',build/'Release/arm7_callee_checks.exe') if p.exists())
    run = subprocess.run([str(executable),str(image)],capture_output=True,text=True,timeout=15)
    assert run.returncode == 0, run.stdout+run.stderr
