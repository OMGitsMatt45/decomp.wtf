"""Original synthetic programs prove native alternatives without code mutation."""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess
import sys
import pytest

from decompnet import toolchains
from decompnet.nds_native import export
from .fixtures.nds_static import simple

CHECKS=r'''
#include <dsr/session.h>
#include <dsr/rt.h>
#include "profile.hpp"
#include "cheats.hpp"
#include <iostream>
#include <stdexcept>
void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(int argc,char** argv){try {
    require(argc==3,"assets/save arguments missing");
    dsr::MachineConfig config;config.rom_path=std::filesystem::path(argv[1])/"game.nds";
    config.save_path=argv[2];config.guest_abi.backup_type=dsr::BackupType::Eeprom8K;
    config.arm9_table=dsr::gen_table_arm9();config.arm7_table=dsr::gen_table_arm7();
    profile::configure(config);
    dsr::Session first(config);profile::initialize(first.machine());
    auto& a=first.machine();constexpr auto cpu=dsr::CpuId::Arm9;
    first.step({});
    require(a.read32(cpu,0x02010000)==1&&a.read32(cpu,0x02010004)==0&&a.read32(cpu,0x02010008)==0xe3a02001,"disabled alternatives changed the original path");
    require(!a.select_instruction_choice(999,0,11)&&!a.select_instruction_choice(0,0xe1a0beef,11)&&!a.select_instruction_choice(0,0xe3a00007,0),"unknown or unowned native option accepted");
    require(a.select_instruction_choice(0,0xe3a00007,11)&&a.select_instruction_choice(1,0xe1a00000,11)&&a.select_instruction_choice(2,0xe3a02009,11),"reviewed options rejected");
    first.step({});
    require(a.read32(cpu,0x02010000)==7&&a.read32(cpu,0x02010004)==42&&a.read32(cpu,0x02010008)==0xe3a02009,"compiled arithmetic, new fallthrough or selected literal failed");
    require(a.read32(cpu,0x02000004)==0xe3a00001&&a.read32(cpu,0x0200000c)==0xea000001&&a.read32(cpu,0x02000030)==0xe3a02001,"instruction selection modified guest code bytes");
    config.save_path=std::filesystem::path(argv[2]).string()+".second";
    dsr::Session second(config);profile::initialize(second.machine());second.step({});
    require(second.machine().read32(cpu,0x02010000)==1,"native option leaked between machine instances");
    a.clear_instruction_choices(12);first.step({});
    require(a.read32(cpu,0x02010000)==7,"a different owner cleared the option");
    a.clear_instruction_choices(11);first.step({});
    require(a.read32(cpu,0x02010000)==1&&a.read32(cpu,0x02010008)==0xe3a02001,"disabling did not restore original execution");
    ds_host::MemoryProgramHost host(config);
    auto run=[&](std::initializer_list<ds_host::MemoryProgram::Line> lines) {
        ds_host::MemoryProgram program;program.lines=lines;program.validate();return host.apply(program,a,21);
    };
    run({{0x02000004,0xe3a00007},{0x0200000c,0xe1a00000},{0x02000030,0xe3a02009}});
    first.step({});require(a.read32(cpu,0x02010000)==7,"memory program did not select compiled execution");
    run({{0x52000004,0xe3a00007},{0x02011010,42},{0xd2000000,0}});
    require(a.read32(cpu,0x02011010)==42,"code guards did not read the selected native value");
    require(a.read32(cpu,0x02000004)==0xe3a00001,"memory program changed physical instructions");
    a.clear_instruction_choices(21);
    bool rejected=false;try{run({{0x02011014,123},{0x02000004,0xe3a00009}});}catch(const std::runtime_error&){rejected=true;}
    require(rejected&&a.read32(cpu,0x02011014)==0&&a.instruction_choice(0,0xe3a00001)==0xe3a00001,"invalid code plan was partially committed");
    rejected=false;try{run({{0x02011014,123},{0xb2011018,0},{0xd6000000,0}});}catch(const std::runtime_error&){rejected=true;}
    require(rejected&&a.read32(cpu,0x02011014)==0,"invalid pointer plan was partially committed");
    run({{0xd3000000,0x02011000},{0xd5000000,0x11223344},{0xc0000000,2},{0xd6000000,0},{0xd2000000,0}});
    for(unsigned i=0;i<3;++i)require(a.read32(cpu,0x02011000+4*i)==0x11223344,"loop/offset data writes differ");
    run({{0x52011020,1},{0xe2011024,8},{0xd2000000,0x11111111},{0xd2000000,0},{0x0201102c,42}});
    require(a.read32(cpu,0x02011024)==0&&a.read32(cpu,0x0201102c)==42,"skipped inline payload was executed");
    a.write16(cpu,0x02011040,0xa5f0);
    run({{0x92011040,0xff0000f0},{0x22011044,99},{0xd2000000,0}});
    require(a.read8(cpu,0x02011044)==99,"masked halfword condition differs");
    rejected=false;try{run({{0xc0000000,65535},{0x22011048,88},{0xd2000000,0}});}catch(const std::runtime_error&){rejected=true;}
    require(rejected&&a.read8(cpu,0x02011048)==0,"loop budget allowed partial writes");
    const auto catalog=std::filesystem::path(argv[2]).parent_path()/"programs.txt";
    {std::ofstream out(catalog);out<<"rom "<<profile::asset_sha256<<"\nchoices "<<config.instruction_choices.sha256
      <<"\ncheat \"Native\"\ngroup \"exclusive\"\nar 0x02000004 0xe3a00007\nend\n"
      <<"cheat \"Other\"\ngroup \"exclusive\"\nwrite32 0x0201104c 9\nend\n";}
    ds_host::Cheats cheats;cheats.load(catalog,profile::asset_sha256,config);
    cheats.enable("Native");cheats.apply(a);require(a.instruction_choice(0,0xe3a00001)==0xe3a00007,"catalog program did not activate");
    cheats.enable("Other");cheats.apply(a);
    require(cheats.enabled_count()==1&&a.instruction_choice(0,0xe3a00001)==0xe3a00001&&a.read32(cpu,0x0201104c)==9,"exclusive group did not restore disabled owner's code");
    cheats.enable("Native");cheats.prepare(a,true);
    require(a.instruction_choice(0,0xe3a00001)==0xe3a00007,"boot-time program was not armed before execution");
    cheats.toggle(0);cheats.prepare(a);
    require(a.instruction_choice(0,0xe3a00001)==0xe3a00001,"disabled owner remained active for the next guest step");
    std::cout<<"Compiled alternatives, fallthrough, literal reads, owner clearing, per-machine isolation and original guest bytes passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
'''

def fixture():
    words=[0xe59f4020,0xe3a00001,0xe5840000,0xea000001,
           0xe3a0002a,0xe5840004,0xe59f1010,0xe5841008,0xeafffff6,
           0xe1a00000,0x02010000,0xe1a00000,0xe3a02001]
    raw,profile=simple(struct.pack('<13I',*words),struct.pack('<I',0xeafffffe),code_size9=36)
    profile.pop('hooks',None);profile.pop('save_region',None)
    sites=[]
    for offset,old,new in [(4,words[1],0xe3a00007),(12,words[3],0xe1a00000),(48,words[12],0xe3a02009)]:
        sites.append(dict(cpu='arm9',module=-1,address=0x02000000+offset,width=4,thumb=False,original=old,values=[new]))
    policy=dict(schema='decomp.wtf.nds-instruction-choices/v1',input_sha256=hashlib.sha256(raw).hexdigest(),sites=sites)
    return raw,profile,policy

@pytest.fixture(scope='module')
def sdk():
    if toolchains.installed('dsr-sdk') is None:
        if os.environ.get('DECOMP_REQUIRE_DS_NATIVE')=='1':pytest.fail('Install the pinned DS native runtime')
        pytest.skip('Optional DS native runtime is not installed')
    return toolchains.require('dsr-sdk')

def test_native_choices(tmp_path,sdk):
    raw,profile,policy=fixture();rom=tmp_path/'original.nds';rom.write_bytes(raw)
    reviewed=tmp_path/'reviewed.json';reviewed.write_text(json.dumps(profile))
    root=tmp_path/'Choice project'
    report=export(rom,root,profile=reviewed,instruction_choices=policy,save_type='eeprom8k')
    assert report['integrity_verified']
    assert report['manifest']['fallback']==dict(interpreter=False,runtime_compilation=False)
    assert all(x['undefined_sites']==0 for x in report['manifest']['code_generation'])
    (root/'tests/instruction_choices.cpp').write_text(CHECKS)
    with (root/'CMakeLists.txt').open('a') as file:
        file.write('''
file(GLOB_RECURSE CHOICE_GAME_SOURCES CONFIGURE_DEPENDS game/*.cpp)
add_executable(instruction_choice_checks tests/instruction_choices.cpp ${CHOICE_GAME_SOURCES})
target_include_directories(instruction_choice_checks PRIVATE native)
target_link_libraries(instruction_choice_checks PRIVATE ds_runtime)
''')
    commands=[[sys.executable,'-I',str(root/'tools/extract_assets.py'),str(rom)],
              ['cmake','-S',str(root),'-B',str(root/'build'),'-DNDS_WITH_SDL=OFF','-DCMAKE_BUILD_TYPE=Release'],
              ['cmake','--build',str(root/'build'),'--config','Release','--target','instruction_choice_checks','--parallel','2']]
    for command in commands:
        run=subprocess.run(command,capture_output=True,text=True,timeout=300)
        assert run.returncode==0,run.stdout+run.stderr
    candidates=[root/'build/instruction_choice_checks',root/'build/Release/instruction_choice_checks.exe']
    executable=next(p for p in candidates if p.exists())
    run=subprocess.run([str(executable),str(root/'assets'),str(tmp_path/'isolated-test.sav')],capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr

@pytest.mark.parametrize('change,match',[
    ('identity','identity'),('bytes','original bytes'),('duplicate','Duplicate'),
    ('mode','boundary'),('loop','backward checkpoint'),
])
def test_invalid_choice_policies(tmp_path,sdk,change,match):
    from decompnet.pc import PCError
    raw,profile,policy=fixture();rom=tmp_path/'original.nds';rom.write_bytes(raw)
    reviewed=tmp_path/'reviewed.json';reviewed.write_text(json.dumps(profile))
    if change=='identity':policy['input_sha256']='0'*64
    elif change=='bytes':policy['sites'][0]['original']^=1
    elif change=='duplicate':policy['sites'].append(dict(policy['sites'][0]))
    elif change=='mode':policy['sites'][0]['thumb']=True
    elif change=='loop':policy['sites'][0]['values']=[0xeafffffe]
    with pytest.raises((PCError,ValueError),match=match):
        export(rom,tmp_path/'output',profile=reviewed,instruction_choices=policy)
    assert not (tmp_path/'output').exists()
