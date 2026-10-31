"""A direct ARM7 callee omitted from the input manifest must still execute."""
import json
import struct
import subprocess

from decompnet import nds_native
from decompnet.nds_native.callbacks import recover
from .test_nds_native import sdk, hardware_project  # noqa: F401


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
