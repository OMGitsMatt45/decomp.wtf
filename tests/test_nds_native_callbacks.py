"""Original callbacks in data-classified initialized DS module bytes."""
import copy
import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest

from decompnet import nds_native
from decompnet.nds_native.callbacks import recover,complete,codec_functions,arm7_executable_ranges,_coalesce_dispatch_regions
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


def interworking_image(tmp_path,cpu='arm9',variant='valid',broad=False,external=False):
    base=0x0201e000;raw=bytearray(0xa0)
    # Original Thumb caller, aligned BX-PC veneer, ARM literal-load tail and
    # Thumb leaf. No retail or vendor SDK payloads are used.
    # The caller owns a 256-byte frame, including its saved registers.
    struct.pack_into('<8H',raw,0,0xb510,0xb0be,0x245a,0xf000,0xf80b,0x3001,0xb03e,0xbd10)
    struct.pack_into('<2H',raw,0x20,0x4778,0x46c0)
    struct.pack_into('<3I',raw,0x24,0xe59fc000,0xe12fff1c,base+0x41)
    struct.pack_into('<2H',raw,0x40,0x2029,0x4770)
    functions=[dict(addr=base,size=16,thumb=True,name='caller'),
               dict(addr=base+0x20,size=2,thumb=True,name='veneer'),
               dict(addr=base+0x40,size=4,thumb=True,name='leaf')]
    if variant=='unreferenced':
        functions.pop(1);struct.pack_into('<2H',raw,6,0x46c0,0x46c0)
    if variant=='non_pc':struct.pack_into('<H',raw,0x20,0x4700)
    if variant=='invalid_arm':struct.pack_into('<I',raw,0x24,0xe7f000f0)
    path=tmp_path/'original-interworking.bin';path.write_bytes(raw)
    module=dict(name='original',module_id=3,base=base,image=str(path),functions=functions,
        labels=[],calls=[],code_ranges=[[base,base+16],[base+0x20,base+0x22],[base+0x40,base+0x44]],
        data_ranges=[[base+16,base+0x20],[base+0x22,base+0x40],[base+0x44,base+len(raw)]])
    if broad:
        functions[0]['size']=0x44
        module['dispatch_regions']=[dict(addr=base,size=0x44,thumb=True,
            data_ranges=[[base+16,base+0x20],[base+0x22,base+0x40]],entries=[base,base+0x20,base+0x40])]
    if external:
        assert broad
        struct.pack_into('<I',raw,0x2c,base+0x81)
        struct.pack_into('<2H',raw,0x80,0x2029,0x4770)
        functions[-1]['addr']=base+0x80
        module['dispatch_regions'][0]['entries'].remove(base+0x40)
        module['dispatch_regions'][0]['data_ranges'][-1][1]=base+0x44
        module['code_ranges'][-1]=[base+0x80,base+0x84]
        module['data_ranges']=[[base+16,base+0x20],[base+0x22,base+0x80],[base+0x84,base+len(raw)]]
        path.write_bytes(raw)
    return dict(cpu=cpu,arch='v5te'if cpu=='arm9'else 'v4t',modules=[module]),path


@pytest.mark.parametrize('variant',['unreferenced','non_pc','invalid_arm'])
def test_mode_bridge_needs_an_existing_bx_pc_entry_and_a_valid_arm_graph(tmp_path,sdk,variant):
    manifest,image=interworking_image(tmp_path,variant=variant);before=image.read_bytes()
    _,emitter,reader=nds_native._sdk()
    assert recover(manifest,emitter,reader)==[]
    assert image.read_bytes()==before


def test_mode_bridge_does_not_seed_another_overlay_with_the_same_virtual_address(tmp_path,sdk):
    manifest,_=interworking_image(tmp_path);other=copy.deepcopy(manifest['modules'][0]);other['module_id']=4
    other['functions']=[f for f in other['functions']if f['name']!='veneer']
    manifest['modules'].append(other)
    _,emitter,reader=nds_native._sdk();added=recover(manifest,emitter,reader)
    assert [(r['module_id'],r['address'],r['thumb'])for r in added]==[(3,0x0201e024,False)]


def test_mode_bridge_preserves_existing_reachable_thumb_instructions(tmp_path,sdk):
    manifest,image=interworking_image(tmp_path);raw=bytearray(image.read_bytes())
    struct.pack_into('<I',raw,0x24,0xe1a00000);image.write_bytes(raw)
    # The first halfword is an existing Thumb LSLS instruction as well as
    # part of a possible ARM MOV. A state-changing root must not replace it.
    manifest['modules'][0]['functions'].append(dict(addr=0x0201e024,size=2,thumb=True,name='existing_thumb'))
    _,emitter,reader=nds_native._sdk()
    assert recover(manifest,emitter,reader)==[]


@pytest.mark.parametrize('cpu',['arm9','arm7'])
@pytest.mark.parametrize('broad,external',[(False,False),(True,False),(True,True)])
def test_thumb_bx_pc_continuation_executes_arm_literal_tail_and_returns_to_thumb(tmp_path,sdk,hardware_project,cpu,broad,external):
    manifest,image=interworking_image(tmp_path,cpu,broad=broad,external=external);before=image.read_bytes();base=manifest['modules'][0]['base']
    _,emitter,reader=nds_native._sdk();added=recover(manifest,emitter,reader)
    assert len(added)==1 and added[0]['address']==base+0x24 and not added[0]['thumb']
    assert added[0]['call_sources']==[dict(module_id=3,address=base+0x20)]
    assert recover(manifest,emitter,reader)==[]
    module=manifest['modules'][0]
    assert any(low<=base+0x2c<high for low,high in module['data_ranges'])
    assert all(not low<=base+0x24<high for low,high in module['data_ranges'])
    assert emitter.emit_manifest(manifest,tmp_path/'generated')['undefined_sites']==0
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
 dsr::MachineConfig config;config.direct_boot=false;config.CPU_table=dsr::gen_table_CPU();
 dsr::Machine machine(config);auto& c=machine.cpu(dsr::CpuId::ID);
 std::ifstream file(argv[1],std::ios::binary);
 std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
 for(unsigned i=0;i<bytes.size();++i)machine.write8(dsr::CpuId::ID,0x0201e000+i,bytes[i]);
 c.budget=10000;c.r[0]=0;for(unsigned i=4;i<12;++i)c.r[i]=0xcafe0000+i;c.r[13]=0x02030000;c.r[14]=0x02001001;
 dsr::dsr_call(&c,0x0201e001);
 if(c.r[0]!=42||c.r[13]!=0x02030000||!(dsr::dsr_mrs_cpsr(&c)&0x20))return 1;
 for(unsigned i=4;i<12;++i)if(c.r[i]!=0xcafe0000+i)return 3;
 for(unsigned i=0;i<bytes.size();++i)if(machine.read8(dsr::CpuId::ID,0x0201e000+i)!=bytes[i])return 2;
 return 0;
}
'''.replace('CPU',cpu).replace('ID','Arm9'if cpu=='arm9'else 'Arm7'))
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(ModeBridgeChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\n'
        'file(GLOB GENERATED generated/*.cpp)\nadd_executable(mode_checks checks.cpp ${GENERATED})\n'
        f'target_include_directories(mode_checks PRIVATE generated {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(mode_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(mode_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    executable=next(p for p in (build/'mode_checks',build/'Release/mode_checks.exe')if p.exists())
    done=subprocess.run([str(executable),str(image)],capture_output=True,text=True,timeout=15)
    assert done.returncode==0,done.stdout+done.stderr
    assert image.read_bytes()==before


def test_hashed_reference_reclaims_a_thumb_root_after_an_arm_veneer_literal(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk()
    base=0x0201D000;raw=bytearray(0x80)
    struct.pack_into('<2I',raw,0x20,0xE51FF004,0x02700100)
    struct.pack_into('<2H',raw,0x28,0x2007,0x4770)
    image=tmp_path/'original-veneer-literal.bin';image.write_bytes(raw)
    module=dict(name='original',module_id=5,base=base,image=str(image),
        functions=[dict(addr=base+0x20,size=4,thumb=False,name='veneer'),
                   dict(addr=base+0x24,size=8,thumb=True,name='bad_importer_prefix')],
        labels=[],calls=[],code_ranges=[[base+0x20,base+0x2c]],data_ranges=[])
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    reference=dict(module_id=5,address=base+0x28,size=4,thumb=True,module_sha256=hashlib.sha256(raw).hexdigest())
    assert recover(manifest,emitter,reader,reference_entries=[reference])==[]
    assert module['functions'][1]['addr']==base+0x28
    assert module['functions'][1]['size']==4
    assert module['data_ranges']==[[base+0x24,base+0x28]]
    assert Path(module['image']).read_bytes()==raw
    assert emitter.emit_manifest(manifest,tmp_path/'generated')['undefined_sites']==0
    bad=copy.deepcopy(manifest);bad['modules'][0]['functions'][1].update(addr=base+0x24,size=8)
    wrong={**reference,'module_sha256':'0'*64}
    with pytest.raises(ValueError,match='SHA-256 differs'):
        recover(bad,emitter,reader,reference_entries=[wrong])
    assert bad['modules'][0]['functions'][1]['addr']==base+0x24


def test_arm7_prologue_scans_need_reference_evidence_before_becoming_entries(tmp_path,sdk):
    from types import SimpleNamespace
    _,emitter,reader=nds_native._sdk()
    base=0x03800000;raw=bytearray(0x80)
    struct.pack_into('<I',raw,0,0xE12FFF1E)
    struct.pack_into('<I',raw,0x10,base+0x40)
    struct.pack_into('<3I',raw,0x40,0xE92D4000,0xE3A00017,0xE8BD8000)
    image=tmp_path/'original-scan-evidence.bin';image.write_bytes(raw)
    functions=[dict(addr=base,size=4,thumb=False,name='root'),dict(addr=base+0x40,size=12,thumb=False,name='scan')]
    state=SimpleNamespace(module_id=-5,base=base,loaded_size=len(raw),executable_ranges=[(0,len(raw))],data_ranges=[],
        functions={(0,base,False):functions[0],(0,base+0x40,False):functions[1]},
        function_evidence={(0,base,False):{'caller-supplied entry'},(0,base+0x40,False):{'validated ARM prologue scan'}},
        function_code={(0,base,False):set(range(base,base+4)),(0,base+0x40,False):set(range(base+0x40,base+0x4c))})
    module=dict(name='original',module_id=-5,base=base,image=str(image),functions=copy.deepcopy(functions),
        labels=[],calls=[{'from':base+0x44,'to':base,'modules':[-5]}],code_ranges=[[base,base+0x80]],data_ranges=[[base+4,base+0x80]])
    manifest=dict(cpu='arm7',arch='v4t',modules=[module])
    arm7_executable_ranges(manifest,[state])
    assert [f['addr']for f in module['functions']]==[base]
    assert module['calls']==[]
    assert module['discarded_prologue_only_roots']==[dict(address=base+0x40,size=12,thumb=False,
        module_sha256=hashlib.sha256(Path(module['image']).read_bytes()).hexdigest())]
    assert [r['address']for r in recover(manifest,emitter,reader)]==[base+0x40]
    assert image.read_bytes()==raw


def instruction_state_image(tmp_path):
    base=0x0201c000;raw=bytearray(0xa0)
    struct.pack_into('<I',raw,0,0xe12fff1e)
    struct.pack_into('<2I',raw,0x10,base+0x21,base+0x61)
    # A pointer-shaped data word leads to a Thumb branch into an ARM owner.
    struct.pack_into('<2H',raw,0x20,0x2007,0xe012)
    struct.pack_into('<4I',raw,0x40,0xe3a00025,0xe12fff1e,0xe7f000f0,0)
    # A same-state branch to an existing Thumb instruction remains callable.
    struct.pack_into('<2H',raw,0x60,0x2005,0xe00f)
    struct.pack_into('<4H',raw,0x80,0x2063,0x3001,0x3003,0x4770)
    path=tmp_path/'original-instruction-state.bin';path.write_bytes(raw)
    return dict(name='state',module_id=7,base=base,image=str(path),
        functions=[dict(addr=base,size=4,thumb=False,name='entry'),
                   dict(addr=base+0x40,size=16,thumb=False,name='arm_owner'),
                   dict(addr=base+0x80,size=8,thumb=True,name='thumb_owner')],
        labels=[],calls=[],code_ranges=[[base,base+len(raw)]],
        data_ranges=[[base+4,base+0x40],[base+0x50,base+0x80],[base+0x88,base+len(raw)]])


def test_callback_edges_preserve_instruction_state(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk();module=instruction_state_image(tmp_path);base=module['base']
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    added=recover(manifest,emitter,reader)
    assert (base+0x20,True) not in {(f['addr'],f['thumb']) for f in module['functions']}
    assert (base+0x60,True) in {(f['addr'],f['thumb']) for f in module['functions']}
    assert {item['address'] for item in added}=={base+0x60}


def test_inferred_entries_preserve_instruction_state(tmp_path,sdk):
    _,emitter,_=nds_native._sdk();module=instruction_state_image(tmp_path);base=module['base']
    raw=bytearray(Path(module['image']).read_bytes())
    struct.pack_into('<2H',raw,0x24,0x2001,0xe00f)
    struct.pack_into('<I',raw,0x08,0xfa00001d)  # ARM BLX changes to the Thumb owner.
    Path(module['image']).write_bytes(raw)
    module['functions'] += [dict(addr=base+o,size=4,thumb=True,name=f'source_{o:x}') for o in (0x20,0x24,0x60)]
    module['functions'].append(dict(addr=base+8,size=4,thumb=False,name='state_change'))
    module['calls']=[{'from':base+s,'to':base+t,'modules':[7]} for s,t in ((0x22,0x4a),(0x26,0x48),(0x62,0x84))]
    module['calls'].append({'from':base+8,'to':base+0x84,'modules':[7]})
    module['entry_points']=[dict(addr=base+0x44,thumb=False)]
    entries,_,_,calls=emitter._prepare_entries(dict(cpu='arm9',arch='v5te',modules=[module]),None)
    keys={(e.address,e.thumb) for e in entries}
    assert (base+0x4a,False) not in keys
    assert (base+0x48,False) not in keys
    assert (base+0x84,True) in keys and (base+0x44,False) in keys
    assert calls[(7,base+0x22)]==[7]


def prepare(tmp_path):
    _,emitter,reader=nds_native._sdk()
    manifest=dict(cpu='arm9',arch='v5te',modules=[callback_image(tmp_path)])
    return manifest,emitter,reader


def reference_image(tmp_path,module_id=4):
    base=0x02018000;raw=bytearray(0x80)
    struct.pack_into('<I',raw,0,0xe12fff1e)
    struct.pack_into('<2I',raw,0x10,base+0x21,base+0x45)
    # A genuine callback's epilogue was imported as a separate fragment.
    struct.pack_into('<4H',raw,0x20,0xb510,0x2429,0x1c20,0xbd10)
    # A second callback follows the return inside an overly broad extent.
    struct.pack_into('<4H',raw,0x40,0xb500,0xbd00,0x2009,0x4770)
    path=tmp_path/f'reference-{module_id}.bin';path.write_bytes(raw)
    module=dict(name=f'ov{module_id:03}',module_id=module_id,base=base,image=str(path),
        functions=[dict(addr=base,size=4,thumb=False,name='entry'),
                   dict(addr=base+0x26,size=2,thumb=True,name='partial_epilogue'),
                   dict(addr=base+0x40,size=8,thumb=True,name='broad_extent')],
        labels=[],calls=[],code_ranges=[[base,base+4],[base+0x26,base+0x28],[base+0x40,base+0x48]],
        data_ranges=[[base+4,base+0x26],[base+0x28,base+0x40]])
    refs=[dict(module_id=module_id,address=base+offset,size=size,thumb=True,
               module_sha256=hashlib.sha256(raw).hexdigest()) for offset,size in ((0x20,8),(0x44,4))]
    return module,refs


def overlapping_region_image(tmp_path,module_id=6):
    base=0x0201a000;raw=bytearray(0x60)
    struct.pack_into('<I',raw,0,0xe12fff1e)
    # The outer callback calls a nested callback and then returns its result.
    struct.pack_into('<4H',raw,0x18,0xb500,0xf000,0xf801,0xbd00)
    # Mutable literal; preserve r4 and the guest stack across both callbacks.
    struct.pack_into('<5H',raw,0x20,0xb510,0x4c03,0x3401,0x1c20,0xbd10)
    struct.pack_into('<I',raw,0x30,41)
    path=tmp_path/f'overlap-{module_id}.bin';path.write_bytes(raw)
    return dict(name=f'ov{module_id:03}',module_id=module_id,base=base,image=str(path),
        functions=[dict(addr=base,size=4,thumb=False,name='entry'),
                   dict(addr=base+0x18,size=0x1c,thumb=True,name='outer'),
                   dict(addr=base+0x20,size=0x14,thumb=True,name='nested')],
        labels=[],calls=[],code_ranges=[[base,base+4],[base+0x18,base+0x2a]],data_ranges=[],
        dispatch_regions=[dict(addr=base+0x18,size=0x1c,thumb=True,
            entries=[base+0x18],data_ranges=[[base+0x20,base+0x34]]),
            dict(addr=base+0x20,size=0x14,thumb=True,entries=[base+0x20],
                 data_ranges=[[base+0x2a,base+0x34]])])


def test_overlapping_regions_keep_union_of_code_and_only_common_data():
    outer=dict(addr=0x1000,size=32,thumb=True,entries=[0x1000],data_ranges=[[0x1004,0x1010]])
    inner=dict(addr=0x1004,size=20,thumb=True,entries=[0x1004],data_ranges=[[0x1008,0x1010]])
    arm=dict(addr=0x1000,size=4,thumb=False,entries=[0x1000],data_ranges=[])
    adjacent=dict(addr=0x1020,size=4,thumb=True,entries=[0x1020],data_ranges=[])
    before=copy.deepcopy([outer,inner,arm,adjacent])
    result=_coalesce_dispatch_regions(before)
    assert before==[outer,inner,arm,adjacent]
    assert result==[arm,{**outer,'entries':[0x1000,0x1004],'data_ranges':[[0x1008,0x1010]]},adjacent]
    assert _coalesce_dispatch_regions(result+result)==result
    with pytest.raises(ValueError,match='outside code bytes'):
        _coalesce_dispatch_regions([{**inner,'entries':[0x1008]}])


def test_complete_coalesces_scanner_growth_around_existing_region(tmp_path,sdk,monkeypatch):
    _,emitter,reader=nds_native._sdk();module=overlapping_region_image(tmp_path)
    smaller=copy.deepcopy(module['dispatch_regions'][1]);larger=copy.deepcopy(module['dispatch_regions'][0])
    module['dispatch_regions']=[smaller]
    class Growth:
        def __init__(self,modules,ranges):
            self.added=[]
            modules[0]['dispatch_regions']=[copy.deepcopy(larger)]
    monkeypatch.setattr(reader,'_GapDiscovery',Growth)
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    expected={**larger,'entries':[module['base']+0x18,module['base']+0x20],
              'data_ranges':smaller['data_ranges']}
    assert complete(manifest,emitter,reader)==dict(callbacks=[],gaps=[])
    assert module['dispatch_regions']==[expected]
    assert complete(manifest,emitter,reader)==dict(callbacks=[],gaps=[])
    assert module['dispatch_regions']==[expected]


def test_reference_bounds_recover_split_and_folded_callbacks_without_overlay_guessing(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk()
    module,refs=reference_image(tmp_path)
    other,_=reference_image(tmp_path,5)
    manifest=dict(cpu='arm9',arch='v5te',modules=[module,other])
    assert recover(copy.deepcopy(manifest),emitter,reader)==[]
    added=recover(manifest,emitter,reader,reference_entries=refs)
    assert {(row['module_id'],row['address']) for row in added}=={(4,0x02018020),(4,0x02018044)}
    assert all(row['reference_module_sha256']==refs[0]['module_sha256'] for row in added)
    assert {row['reference_size'] for row in added}=={4,8}
    assert recover(manifest,emitter,reader,reference_entries=refs)==[]


@pytest.mark.parametrize('change,match',[
    ({'module_sha256':'0'*64},'SHA-256 differs'),
    ({'module_id':99},'module is missing'),
    ({'address':0x02018021},'unaligned'),
    ({'size':0x100},'exceeds'),
    ({'thumb':1},'instruction mode'),
    ({'address':0x02018042,'size':2},'existing reachable instructions'),
])
def test_reference_callback_hints_require_exact_valid_input(tmp_path,sdk,change,match):
    _,emitter,reader=nds_native._sdk();module,refs=reference_image(tmp_path)
    with pytest.raises(ValueError,match=match):
        recover(dict(cpu='arm9',arch='v5te',modules=[module]),emitter,reader,
                reference_entries=[{**refs[0],**change}])


def test_reference_callbacks_still_reject_unsupported_graphs_and_overlapping_hints(tmp_path,sdk):
    _,emitter,reader=nds_native._sdk();module,refs=reference_image(tmp_path)
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    with pytest.raises(ValueError,match='overlapping reference'):
        recover(copy.deepcopy(manifest),emitter,reader,reference_entries=[refs[0],{**refs[0],'address':0x02018022}])
    raw=bytearray(Path(module['image']).read_bytes());struct.pack_into('<H',raw,0x20,0xde00)
    Path(module['image']).write_bytes(raw)
    refs[0]['module_sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='instruction-graph validation'):
        recover(manifest,emitter,reader,reference_entries=refs[:1])


def test_arm7_recovery_excludes_autoload_source_payload(tmp_path,sdk):
    from types import SimpleNamespace
    _,emitter,reader=nds_native._sdk()
    base=0x02380000;raw=bytearray(0x80)
    struct.pack_into('<I',raw,0,0xe12fff1e)
    struct.pack_into('<3I',raw,0x10,base+0x20,base+0x40,base+0x2c)
    struct.pack_into('<2I',raw,0x20,0xe3a00029,0xe12fff1e)
    # A relocated routine's source bytes also look like valid executable code.
    struct.pack_into('<2I',raw,0x40,0xe3a00029,0xe12fff1e)
    # This candidate falls through across the executable boundary.
    struct.pack_into('<2I',raw,0x2c,0xe3a00001,0xe12fff1e)
    image=tmp_path/'autoload-source.bin';image.write_bytes(raw)
    module=dict(name='arm7main',module_id=-4,base=base,image=str(image),
        functions=[dict(addr=base,thumb=False,size=4,name='entry')],labels=[],calls=[],
        code_ranges=[[base,base+4]],data_ranges=[[base+4,base+len(raw)]],
        executable_ranges=[])
    manifest=dict(cpu='arm7',arch='v4t',modules=[module])
    state=SimpleNamespace(module_id=-4,base=base,loaded_size=len(raw),
        executable_ranges=[(0,len(raw))],
        data_ranges=[(0x30,len(raw),'autoload source payload'),(0x10,0x20,'literal pool')])
    arm7_executable_ranges(manifest,[state])
    assert module['executable_ranges']==[[base,base+0x30]]
    assert [item['address'] for item in recover(manifest,emitter,reader)]==[base+0x20]
    assert any(low<=base+0x40<high for low,high in module['data_ranges'])
    assert recover(manifest,emitter,reader)==[]
    module['executable_ranges']=[[base,base+len(raw)+4]]
    with pytest.raises(ValueError,match='executable range exceeds'):
        recover(manifest,emitter,reader)


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


def test_codec_boundaries_replace_broad_guesses_and_keep_pools_as_data(tmp_path,sdk):
    _,_,reader=nds_native._sdk();module=mutable_image(tmp_path,2,1);base=module['base']
    module['functions'].append(dict(addr=base+0x1c,size=0x24,thumb=False,name='broad_guess'))
    module['dispatch_regions']=[dict(addr=base+0x1c,size=0x24,thumb=False,data_ranges=[],entries=[base+0x1c])]
    manifest=dict(cpu='arm9',arch='v5te',modules=[module])
    metadata={2:dict(dsprot=dict(unencrypted=dict(version='fixture',functions=[dict(address=base+0x20,size=16,pool_size=4,encryption='unkeyed')])))}
    assert len(codec_functions(manifest,metadata,reader))==1
    assert {f['addr'] for f in module['functions']}=={base,base+0x20}
    assert module['dispatch_regions']==[dict(addr=base+0x20,size=20,thumb=False,data_ranges=[[base+0x30,base+0x34]],entries=[base+0x20])]
    assert any(low<=base+0x30<high for low,high in module['data_ranges'])
    assert all(not low<=base+0x20<high for low,high in module['data_ranges'])
    invalid=copy.deepcopy(metadata);invalid[2]['dsprot']['unencrypted']['functions'][0]['size']=128
    with pytest.raises(ValueError,match='boundary exceeds'):
        codec_functions(manifest,invalid,reader)


@pytest.mark.parametrize('cpu', ['arm9', 'arm7'])
def test_only_referenced_valid_callbacks_reclassify_code_bytes(tmp_path,sdk,cpu):
    manifest,emitter,reader=prepare(tmp_path)
    manifest.update(cpu=cpu,arch='v4t' if cpu=='arm7' else 'v5te')
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
    metadata={i:dict(dsprot=dict(unencrypted=dict(version='fixture',functions=[
        dict(address=0x02016020,size=16,pool_size=4,encryption='unkeyed')
    ]))) for i in (2,3)}
    assert len(codec_functions(manifest,metadata,reader))==2
    assert len(recover(manifest,emitter,reader))==10
    referenced,refs=reference_image(tmp_path)
    manifest['modules'].append(referenced)
    assert len(recover(manifest,emitter,reader,reference_entries=refs))==2
    overlap=overlapping_region_image(tmp_path);manifest['modules'].append(overlap)
    assert recover(manifest,emitter,reader)==[]
    assert len(overlap['dispatch_regions'])==1
    state=instruction_state_image(tmp_path);manifest['modules'].append(state)
    assert {r['address'] for r in recover(manifest,emitter,reader)}=={state['base']+0x60}
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
  for(int i=3;i<=4;++i) {
    std::ifstream file(argv[i],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x02016000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;
    dsr::dsr_call(&cpu,0x02016020);dsr::dsr_call(&cpu,0x02016020);
    if(cpu.r[0]!=41+2*unsigned(i-2))return 5;
  }
  {
    std::ifstream file(argv[5],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x02018000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;cpu.r[4]=0x12345678;
    dsr::dsr_call(&cpu,0x02018021);
    if(cpu.r[0]!=41 || cpu.r[13]!=0x023ff000 || cpu.r[4]!=0x12345678)return 6;
    dsr::dsr_call(&cpu,0x02018045);
    if(cpu.r[0]!=9 || cpu.r[13]!=0x023ff000)return 7;
  }
  {
    std::ifstream file(argv[6],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x0201a000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;cpu.r[4]=0x12345678;
    dsr::dsr_call(&cpu,0x0201a019);
    if(cpu.r[0]!=42 || cpu.r[13]!=0x023ff000 || cpu.r[4]!=0x12345678)return 8;
    machine.write32(dsr::CpuId::Arm9,0x0201a030,77);
    cpu.r[14]=0x02015000; // A new caller, not the previous nested call's LR.
    dsr::dsr_call(&cpu,0x0201a021);
    if(cpu.r[0]!=78 || cpu.r[13]!=0x023ff000 || cpu.r[4]!=0x12345678)return 9;
  }
  {
    std::ifstream file(argv[7],std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    for(unsigned j=0;j<bytes.size();++j)machine.write8(dsr::CpuId::Arm9,0x0201c000+j,bytes[j]);
    cpu.budget=100000;cpu.r[13]=0x023ff000;cpu.r[14]=0x02015000;cpu.r[4]=0x12345678;
    dsr::dsr_call(&cpu,0x0201c061);
    if(cpu.r[0]!=8 || cpu.r[13]!=0x023ff000 || cpu.r[4]!=0x12345678)return 10;
    cpu.r[14]=0x02015000;dsr::dsr_call(&cpu,0x0201c040);
    if(cpu.r[0]!=37 || cpu.r[13]!=0x023ff000)return 11;
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
