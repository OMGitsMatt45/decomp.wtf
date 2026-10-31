"""Original Wi-Fi register transactions exercise the real generated runtime."""
import json
import subprocess
from .test_nds_native import sdk, hardware_project  # noqa: F401


def test_wifi_irq_acknowledgement_and_primary_edge(tmp_path, sdk, hardware_project):
    _, project, _ = hardware_project
    runtime = project / 'native/dsr/runtime'
    libraries = list((project / 'build').rglob('libds_runtime.a')) + list((project / 'build').rglob('ds_runtime.lib'))
    assert len(libraries) == 1
    (tmp_path / 'checks.cpp').write_text(r'''
#include <dsr/machine.h>
#include <dsr/rt.h>
#include <source_location>
#include <stdexcept>
#include <iostream>
using namespace dsr;
void require(bool value, std::source_location site=std::source_location::current()) {
 if(!value) throw std::runtime_error("Wi-Fi IRQ assertion at line "+std::to_string(site.line()));
}
int main() { try {
 MachineConfig config;config.direct_boot=false;Machine m(config);
 constexpr auto arm7=CpuId::Arm7;
 constexpr uint32_t flags=0x04808010,enable=0x04808012,force=0x0480821c,primary=0x04000214;
 m.write16(arm7,0x04000304,2);
 require(m.read16(arm7,flags)==0 && m.read16(arm7,enable)==0);
 m.write16(arm7,force,0x8401); // bit 10 is not a real interrupt
 require(m.read16(arm7,flags)==0x8001 && !(m.read32(arm7,primary)&(1u<<24)));
 m.write16(arm7,enable,0x8001);
 require(m.read32(arm7,primary)&(1u<<24));
 m.write32(arm7,primary,1u<<24);
 require(!(m.read32(arm7,primary)&(1u<<24))); // acknowledge even while W_IF & W_IE stays nonzero
 m.write16(arm7,enable,0x8001);
 require(!(m.read32(arm7,primary)&(1u<<24))); // no repeated level-triggered request
 m.write16(arm7,enable,0);m.write16(arm7,enable,0x8001);
 require(m.read32(arm7,primary)&(1u<<24));
 m.write32(arm7,primary,1u<<24);
 m.write8(arm7,flags+1,0x80); // STRB is ignored throughout wireless I/O and RAM
 require(m.read16(arm7,flags)==0x8001 && !(m.read32(arm7,primary)&(1u<<24)));
 m.write16(arm7,flags,0x8000);require(m.read16(arm7,flags)==1);
 m.write16(arm7,flags,1);require(m.read16(arm7,flags)==0);
 m.write8(arm7,force+1,0x80);require(m.read16(arm7,flags)==0);
 m.write16(arm7,force,0x8000);require(m.read16(arm7,flags)==0x8000);
 require(m.read32(arm7,primary)&(1u<<24));
 m.write16(arm7,flags,0xffff);require(m.read16(arm7,flags)==0);
 m.write8(arm7,enable+1,0x04);require(m.read16(arm7,enable)==0x8001);
 m.write16(arm7,force,0x0400);require(m.read16(arm7,flags)==0);
 // A normal SDK drain loop must terminate on an idle adapter.
 unsigned passes=0;
 while(m.read16(arm7,flags)&m.read16(arm7,enable)) {
  if(++passes>16)throw std::runtime_error("idle Wi-Fi IRQ drain did not terminate");
  m.write16(arm7,flags,m.read16(arm7,flags));
 }
 require(passes==0 && m.unimplemented_io_count()==0);
 // Independent documented latch widths and neighbouring-register isolation.
 for(uint32_t pattern : {0u,0xffffu,0xa55au,0x5aa5u}) {
  m.write16(arm7,0x04808018,pattern);m.write16(arm7,0x0480801a,pattern^0xffffu);
  require(m.read16(arm7,0x04808018)==pattern && m.read16(arm7,0x0480801a)==(pattern^0xffffu));
  m.write16(arm7,0x04808006,pattern);require(m.read16(arm7,0x04808006)==(pattern&0x7fu));
  m.write16(arm7,0x0480802a,pattern);require(m.read16(arm7,0x0480802a)==(pattern&0x7ffu));
  m.write16(arm7,0x04808058,pattern);require(m.read16(arm7,0x04808058)==(pattern&0x1ffeu));
  m.write16(arm7,0x04808132,pattern);require(m.read16(arm7,0x04808132)==(pattern&0x8fffu));
 }
 m.write16(arm7,0x04804000,0x5aa5);m.write8(arm7,0x04804000,0);
 require(m.read16(arm7,0x04804000)==0x5aa5 && m.unimplemented_io_count()==0);
 // BB 0x47 is writable; 0x4d is read-only. The previous bitmap confused them.
 m.write16(arm7,0x0480815a,0xa5);m.write16(arm7,0x04808158,0x5047);
 m.write16(arm7,0x04808158,0x6047);require(m.read16(arm7,0x0480815c)==0xa5);
 m.write16(arm7,0x0480815a,0xff);m.write16(arm7,0x04808158,0x504d);
 m.write16(arm7,0x04808158,0x604d);require(m.read16(arm7,0x0480815c)==0);
 // A disabled RF front-end is idle. A queued wake requires MAC/clock enable.
 require(m.read16(arm7,0x04808000)==0x1440 && m.read16(arm7,0x04808214)==9);
 m.write16(arm7,0x0480803c,2);require(m.read16(arm7,0x0480803c)==0x200);
 m.write16(arm7,0x04808004,1);m.write16(arm7,0x04808036,0);
 m.write16(arm7,0x0480803c,2);
 require(m.read16(arm7,0x0480803c)==0 && (m.read16(arm7,flags)&0x800));
 m.write16(arm7,0x04808040,0x8001);
 require(m.read16(arm7,0x0480803c)==0x200 && m.read16(arm7,0x04808214)==9);
 m.write16(arm7,0x04808040,0x8000);require(m.read16(arm7,0x0480803c)==0x300);
 m.write16(arm7,0x04808040,0x8001);require(m.read16(arm7,0x04808040)==0x8000);
 m.write16(arm7,0x048082d0,0);require(m.read16(arm7,0x0480803c)==0);
 m.write16(arm7,0x04000304,0);m.write16(arm7,force,1);
 require(m.read16(arm7,flags)==0); // disabled wireless power gate
 std::cout<<"Wi-Fi latch masks/isolation, ignored STRB, IRQ edge/ack, idle drain and power gate passed\n";
 } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}}
''')
    quote = lambda path: json.dumps(path.as_posix())
    (tmp_path / 'CMakeLists.txt').write_text(
        'cmake_minimum_required(VERSION 3.20)\nproject(WifiIrqChecks LANGUAGES CXX)\n'
        'set(CMAKE_CXX_STANDARD 20)\nfind_package(Threads REQUIRED)\nadd_executable(wifi_irq_checks checks.cpp)\n'
        f'target_include_directories(wifi_irq_checks PRIVATE {quote(runtime / "include")} {quote(runtime / "core/include")})\n'
        f'target_link_libraries(wifi_irq_checks PRIVATE {quote(libraries[0])} Threads::Threads)\n'
        'if(WIN32)\n target_link_libraries(wifi_irq_checks PRIVATE bcrypt)\nendif()\n')
    build = tmp_path / 'build'
    for command in (['cmake', '-S', str(tmp_path), '-B', str(build)],
                    ['cmake', '--build', str(build), '--config', 'Release', '--parallel', '2']):
        run = subprocess.run(command, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
    executable = next(path for path in (build / 'wifi_irq_checks', build / 'Release/wifi_irq_checks.exe') if path.exists())
    run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
