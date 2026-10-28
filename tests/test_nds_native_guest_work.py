"""Host-to-guest work stays on guest fibers, outside critical/IRQ sections."""
import json
import subprocess
from .test_nds_native import sdk, hardware_project  # noqa: F401


def test_guest_work_yields_preserves_state_and_reports_errors_on_host(tmp_path,sdk,hardware_project):
    _,project,_=hardware_project
    runtime=project/'native/dsr/runtime'
    libraries=list((project/'build').rglob('libds_runtime.a'))+list((project/'build').rglob('ds_runtime.lib'))
    assert len(libraries)==1
    (tmp_path/'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include <dsr/fiber.h>
#include <stdexcept>
#include <vector>
#include <iostream>
#include <source_location>
using namespace dsr;
void require(bool v,const std::source_location& site=std::source_location::current()){if(!v)throw std::runtime_error("guest work assertion failed at line "+std::to_string(site.line()));}
unsigned iterations=0,interrupts=0;
void loop(Cpu* c){for(;;){c->budget=0;dsr_checkpoint(c,0x02001000);++iterations;}}
void irq(Cpu* c){++interrupts;c->m->write32(c->id,0x04000214,1<<5);}
int main(){try{
 GuestFn entry=loop,handler=irq;
 const FnEntry functions[]={{0x02001000,4,-1,0,0,&entry,"loop"},{0x02002000,4,-1,0,0,&handler,"irq"}};
 MachineConfig cfg;cfg.direct_boot=false;cfg.arm9_table={functions,2};Machine m(cfg);
 auto& c=m.cpu(CpuId::Arm9);m.start_cpu(CpuId::Arm9,0x02001000);
 dsr_msr_cpsr(&c,kModeIrq|kCpsrI,0xf);c.r[13]=0x023fe000;
 dsr_msr_cpsr(&c,kModeSys,0xf);c.r[0]=55;c.r[13]=0x023ff000;c.z=1;
 std::vector<unsigned> order;
 m.post_guest_work(c.id,[&](Cpu& work){
  require(Fiber::current()!=nullptr&&&work==&c);order.push_back(1);
  work.r[0]=123;work.r[13]-=64;work.z=0;
  m.write32(work.id,0x02003000,0xfeedbeef);
  m.post_guest_work(work.id,[&](Cpu&){order.push_back(4);});
  work.budget=-7;dsr_checkpoint(&work,0x02001100);
  require(order==std::vector<unsigned>{1});order.push_back(2);
 });
 m.post_guest_work(c.id,[&](Cpu&){order.push_back(3);});
 m.run_ticks(4096);
 require(order==std::vector<unsigned>({1,2,3,4}));
 require(c.r[0]==55&&c.r[13]==0x023ff000&&c.z==1&&iterations>0);
 require(m.read32(c.id,0x02003000)==0xfeedbeef);
 unsigned completed=0;dsr_msr_cpsr(&c,kModeSys|kCpsrI,0xf);
 m.post_guest_work(c.id,[&](Cpu&){++completed;});m.run_ticks(512);require(completed==0);
 dsr_msr_cpsr(&c,kModeSys,0xf);m.run_ticks(512);require(completed==1);
 m.write32(c.id,0x00803ffc,0x02002000);m.write32(c.id,0x04000208,1);m.write32(c.id,0x04000210,1<<5);
 m.raise_irq(c.id,5);m.post_guest_work(c.id,[&](Cpu& work){require(interrupts==1&&(work.cpsr_ctrl&kCpsrModeMask)==kModeSys);++completed;});
 m.run_ticks(512);require(completed==2);
 bool empty=false;try{m.post_guest_work(c.id,{});}catch(const std::invalid_argument&){empty=true;}require(empty);
 for(unsigned i=0;i<64;++i)m.post_guest_work(c.id,[](Cpu&){});
 bool full=false;try{m.post_guest_work(c.id,[](Cpu&){});}catch(const std::length_error&){full=true;}require(full);m.run_ticks(20000);
 m.post_guest_work(c.id,[](Cpu&){throw std::runtime_error("original task failure");});
 bool caught=false;try{m.run_ticks(512);}catch(const std::runtime_error& e){caught=std::string(e.what())=="original task failure";require(Fiber::current()==nullptr);}
 require(caught&&c.r[0]==55&&c.r[13]==0x023ff000);
 std::cout<<"FIFO, yield, reentry, registers, memory, IRQ priority, critical section, bounds and host error passed\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
''')
    quote=lambda p:json.dumps(p.as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(GuestWorkChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\n'
        'add_executable(guest_work_checks checks.cpp)\n'
        f'target_include_directories(guest_work_checks PRIVATE {quote(runtime/"include")} {quote(runtime/"core/include")})\n'
        f'target_link_libraries(guest_work_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(guest_work_checks PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode==0,run.stdout+run.stderr
    exe=next(p for p in (build/'guest_work_checks',build/'guest_work_checks.exe',build/'Release/guest_work_checks.exe') if p.exists())
    run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr
