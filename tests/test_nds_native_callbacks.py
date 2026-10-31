"""Original callbacks in data-classified initialized DS module bytes."""
import copy
import json
import struct
import subprocess
from pathlib import Path

import pytest

from decompnet import nds_native
from decompnet.nds_native.callbacks import recover,complete
from .test_nds_native import sdk, hardware_project  # noqa: F401


def callback_image(tmp_path,module_id=0,increment=1):
    base=0x02014000;raw=bytearray(0x100)
    def words(offset,*values):struct.pack_into('<'+'I'*len(values),raw,offset,*values)
    words(0,0xe12fff1e)
    words(0x10,base+0x40,base+0x61,base+0x70,base+0x80)
    words(0x20,base+0xb1)
    words(0x40,0xe92d4010,0xe59f0008,0xeb000010,0xe8bd8010,0,0x12345678)
    # A prologue-free Thumb callback has two return paths.
    struct.pack_into('<6H',raw,0x60,0x2800,0xd001,0x2009,0x4770,0x2008,0x4770)
    words(0x70,0xe12fff1e)
    words(0x80,0xe92d4000,0xe7f000f0)  # referenced prologue followed by UDF
    words(0x90,0xe2800000|increment,0xe12fff1e)  # directly called leaf
    words(0xa0,0xe92d4000,0xe8bd8000)  # unreferenced prologue stays data
    # A prologue-free Thumb leaf uses a signed halfword dispatch table.
    struct.pack_into('<19H',raw,0xb0,0x2802,0xd80e,0x0041,0x4479,
        0x88c9,0x0409,0x1409,0x448f,4,8,12,
        0x200a,0x4770,0x200b,0x4770,0x200c,0x4770,0x200d,0x4770)
    path=tmp_path/f'original-{module_id}.bin';path.write_bytes(raw)
    return dict(name=f'ov{module_id:03}',module_id=module_id,base=base,image=str(path),
        functions=[dict(addr=base,thumb=False,size=4,name='existing')],labels=[],calls=[],
        code_ranges=[[base,base+4]],data_ranges=[[base+4,base+len(raw)]])


def prepare(tmp_path):
    _,emitter,reader=nds_native._sdk()
    manifest=dict(cpu='arm9',arch='v5te',modules=[callback_image(tmp_path)])
    return manifest,emitter,reader


def mutable_image(tmp_path,module_id,increment):
    base=0x02016000;raw=bytearray(0x40)
    struct.pack_into('<I',raw,0,0xe12fff1e)
    struct.pack_into('<I',raw,0x10,base+0x20)
    struct.pack_into('<5I',raw,0x20,0xe59f0008,0xe2800000|increment,0xe58f0000,0xe12fff1e,41)
    path=tmp_path/f'mutable-{module_id}.bin';path.write_bytes(raw)
    return dict(name=f'ov{module_id:03}',module_id=module_id,base=base,image=str(path),
        functions=[dict(addr=base,thumb=False,size=4,name='existing')],labels=[],calls=[],
        code_ranges=[[base,base+4]],data_ranges=[[base+4,base+len(raw)]])


def test_pc_relative_data_stores_keep_mutable_literals_out_of_dispatch_hashes(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk()
    module=mutable_image(tmp_path,2,1)
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    assert len(recover(manifest,emitter,reader))==1
    region=module['dispatch_regions'][0]
    assert region['data_ranges']==[[0x02016030,0x02016034]]
    # A store into an actual decoded instruction is rejected.
    other=mutable_image(tmp_path,3,1)
    image=bytearray(Path(other['image']).read_bytes())
    struct.pack_into('<I',image,0x28,0xe50f0008)  # str r0,[pc,#-8] -> itself
    Path(other['image']).write_bytes(image)
    assert recover(dict(cpu='arm9',arch='v5te',modules=[other]),emitter,reader)==[]


def test_callback_boundaries_enable_a_later_gap_pass_without_losing_regions(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk()
    module=mutable_image(tmp_path,2,1);base=module['base']
    image=bytearray(Path(module['image']).read_bytes());image.extend(bytes(0x40))
    struct.pack_into('<2I',image,4,0xe3a00011,0xe12fff1e)
    struct.pack_into('<I',image,0x10,0)
    struct.pack_into('<I',image,0x60,base+0x20)
    Path(module['image']).write_bytes(image)
    module['code_ranges']=[[base,base+0x34]]
    module['data_ranges']=[[base+0x60,base+0x80]]
    control=copy.deepcopy(module)
    first=reader._GapDiscovery([control],[control['code_ranges']])
    assert not any(record['addr']==base+4 for record in first.added)
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    result=complete(manifest,emitter,reader)
    assert len(result['callbacks'])==1
    assert any(record['addr']==base+4 for record in result['gaps'])
    assert any(region['addr']==base+0x20 and region['data_ranges']==[[base+0x30,base+0x34]]
               for region in module['dispatch_regions'])
    regions=copy.deepcopy(module['dispatch_regions'])
    assert complete(manifest,emitter,reader)==dict(callbacks=[],gaps=[])
    assert module['dispatch_regions']==regions and len(manifest['callback_recovery'])==1


def test_only_referenced_valid_callbacks_reclassify_code_bytes(tmp_path,sdk):
    manifest,emitter,reader=prepare(tmp_path)
    before=copy.deepcopy(manifest);base=manifest['modules'][0]['base']
    added=recover(manifest,emitter,reader)
    assert {(f['address']-base,f['thumb']) for f in added}=={
        (0x40,False),(0x60,True),(0x70,False),(0x90,False),(0xb0,True)}
    module=manifest['modules'][0]
    assert any(low<=base+0x54<high for low,high in module['data_ranges'])
    assert any(low<=base+0xa0<high for low,high in module['data_ranges'])
    assert any(low<=base+0xc0<high for low,high in module['data_ranges'])
    assert all(not low<=base+0xc6<high for low,high in module['data_ranges'])
    assert all(not low<=base+0x40<high for low,high in module['data_ranges'])
    assert module['functions'][0]==before['modules'][0]['functions'][0]
    assert recover(manifest,emitter,reader)==[]
    arm7={**before,'cpu':'arm7','arch':'v4t'}
    assert recover(arm7,emitter,reader)==[] and arm7['modules']==before['modules']


@pytest.mark.parametrize('targets,source_thumb', [([0],False),([0],True),([0,1],False)])
def test_qualified_direct_calls_seed_only_the_referenced_overlay(tmp_path,sdk,targets,source_thumb):
    _,emitter,reader=nds_native._sdk()
    destination=callback_image(tmp_path,0)
    other=callback_image(tmp_path,1)
    base=0x02001000;target=destination['base']+0xa0
    if source_thumb:
        # Thumb BLX immediate exchanges into ARM code in the named overlay.
        offset=target-(base+4)
        raw=struct.pack('<3H',0xf000|((offset>>12)&0x7ff),0xe800|((offset>>1)&0x7fe),0x4770)
    else:
        raw=struct.pack('<2I',0xeb000000|(((target-base-8)//4)&0xffffff),0xe12fff1e)
    path=tmp_path/'caller.bin';path.write_bytes(raw)
    source=dict(name='main',module_id=-1,base=base,image=str(path),
        functions=[dict(addr=base,size=len(raw),thumb=source_thumb,name='caller')],labels=[],
        code_ranges=[[base,base+len(raw)]],data_ranges=[],
        calls=[dict(**{'from':base,'to':target},modules=targets)])
    manifest=dict(cpu='arm9',arch='v5te',modules=[source,destination,other])
    recovered=recover(manifest,emitter,reader)
    selected=[x for x in recovered if x['address']==target]
    if len(targets)==1:
        assert len(selected)==1 and selected[0]['module_id']==0 and not selected[0]['thumb']
        assert selected[0]['call_sources']==[dict(module_id=-1,address=base)]
    else:
        assert selected==[]


def test_callbacks_execute_statically_and_keep_overlay_image_identity(tmp_path,sdk,hardware_project):
    manifest,emitter,reader=prepare(tmp_path)
    manifest['modules'].append(callback_image(tmp_path,1,increment=2))
    manifest['modules'].extend([mutable_image(tmp_path,2,1),mutable_image(tmp_path,3,2)])
    assert len(recover(manifest,emitter,reader))==12
    generated=tmp_path/'generated';generated.mkdir()
    result=emitter.emit_manifest(manifest,generated,chunk_size=100)
    assert result['undefined_sites']==0
    _,project,_=hardware_project
    libraries=list((project/'build').rglob('libds_runtime.a'))+list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries)==1
    runtime=project/'native/dsr/runtime'
    (tmp_path/'checks.cpp').write_text('''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include "decls.h"
#include <fstream>
#include <vector>
int main(int argc,char** argv) {
  dsr::MachineConfig config;config.direct_boot=false;config.arm9_table=dsr::gen_table_arm9();
  config.arm9_regions=dsr::gen_dispatch_regions_arm9();
  dsr::Machine machine(config);auto& cpu=machine.cpu(dsr::CpuId::Arm9);
  for(int i=1;i<=2;++i) {
    std::ifstream file(argv[i],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x02014000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;
    dsr::dsr_call(&cpu,0x02014040);
    if(cpu.r[0]!=0x12345678u+unsigned(i))return 1;
    dsr::dsr_call(&cpu,0x02014061);
    if(cpu.r[0]!=9 || cpu.r[13]!=0x023ff000)return 2;
    cpu.r[0]=0;dsr::dsr_call(&cpu,0x02014061);
    if(cpu.r[0]!=8)return 3;
    for(unsigned value=0;value<4;++value) {
      cpu.r[0]=value;dsr::dsr_call(&cpu,0x020140b1);
      if(cpu.r[0]!=10+value)return 4;
    }
  }
  for(int i=3;i<argc;++i) {
    std::ifstream file(argv[i],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x02016000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;
    dsr::dsr_call(&cpu,0x02016020);dsr::dsr_call(&cpu,0x02016020);
    if(cpu.r[0]!=41+2*unsigned(i-2))return 5;
  }
}
''')
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(CallbackChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        'find_package(Threads REQUIRED)\nfile(GLOB GENERATED generated/*.cpp)\n'
        'add_executable(callback_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(callback_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(callback_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n')
    with (tmp_path/'CMakeLists.txt').open('a') as file:
        file.write('if(WIN32)\n  target_link_libraries(callback_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode==0,run.stdout+run.stderr
    exe=next(p for p in (build/'callback_checks',build/'callback_checks.exe',
        build/'Release/callback_checks.exe') if p.exists())
    run=subprocess.run([str(exe),*(m['image'] for m in manifest['modules'])],
        capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr
