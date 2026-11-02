"""Original marker cartridges cover retail command address-line behavior."""
import json
import shutil
import subprocess

import pytest

from decompnet.nds_native.card_bus import patch
from .test_nds_native import sdk  # noqa: F401


def test_retail_card_capacity_alias_page_wrap_and_trimmed_padding(tmp_path, sdk):
    root = tmp_path/'r'
    target = root/'runtime/periph/src'
    target.mkdir(parents=True)
    shutil.copyfile(sdk/'runtime/periph/src/periph.cpp', target/'periph.cpp')
    patch(root)
    (tmp_path/'check.cpp').write_text(r'''
#include <dsr/periph.h>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>
std::vector<std::uint8_t> read_block(dsr::GameCard& card,std::uint32_t address) {
 const std::array<std::uint8_t,8> command={0xb7,std::uint8_t(address>>24),
   std::uint8_t(address>>16),std::uint8_t(address>>8),std::uint8_t(address),0,0,0};
 for(unsigned i=0;i<8;++i)card.io_write(0x040001a8+i,command[i],8);
 card.io_write(0x040001a4,0xa1000000,32);
 std::vector<std::uint8_t> result;
 for(unsigned i=0;i<128;++i) {
  card.run(1000);
  if(!(card.io_read(0x040001a4,32)&0x800000))return {};
  auto word=card.io_read(0x04100010,32);
  for(unsigned j=0;j<4;++j)result.push_back(std::uint8_t(word>>(8*j)));
 }
 card.run(1000);
 if(card.io_read(0x040001a4,32)&0x80800000)return {};
 return result;
}
int main(int argc,char** argv) {
 const std::filesystem::path folder=argv[1];
 for(unsigned variant=0;variant<3;++variant) {
  unsigned capacity=variant?0x40000:0x20000;
  std::vector<std::uint8_t> bytes(variant==2?0x18000:capacity);
  for(unsigned i=0;i<bytes.size();++i)bytes[i]=std::uint8_t((i*23)^(i>>8)^(i>>13));
  bytes[0x14]=variant?1:0;
  auto rom=folder/(std::to_string(variant)+".nds");
  {std::ofstream f(rom,std::ios::binary);f.write(reinterpret_cast<char*>(bytes.data()),bytes.size());}
  dsr::GameCard card(rom,folder/(std::to_string(variant)+".sav"),dsr::BackupType::Flash512K);
  // Explicit expected file spans: command, first byte, wrap byte, first span length.
  // These fixtures do not recompute the implementation's masks or redirect rule.
  const std::vector<std::array<std::uint32_t,4>> cases={
   {0x1000,0x8000,0,512},{0x1200,0x8000,0,512},{0x1400,0x8000,0,512},
   {0x1001,0x8001,0,512},{capacity+0x1000,0x8000,0,512},
   {capacity+0x1200,0x8000,0,512},{capacity+0x1400,0x8000,0,512},
   {capacity*3+0x8124,0x8124,0,512},{0x8ffc,0x8ffc,0x8000,4},
   {capacity+0x8fff,0x8fff,0x8000,1},{0xffffffff,capacity-1,capacity-0x1000,1},
   {0x20000,variant?0x20000u:0x8000u,0,512}};
  for(const auto& check:cases) {
   auto block=read_block(card,check[0]);
   if(block.size()!=512)return 1;
   for(unsigned i=0;i<512;++i) {
    auto at=i<check[3]?check[1]+i:check[2]+i-check[3];
    auto expected=at<bytes.size()?bytes[at]:0xff;
    if(block[i]!=expected)return 2;
   }
  }
  // Boot-loader reads retain file offsets and do not use retail mirroring.
  std::uint8_t raw=0;
  card.read_rom(capacity+0x1000,&raw,1);
  if(raw!=0xff)return 3;
  card.read_rom(0x1000,&raw,1);
  if(raw!=bytes[0x1000])return 4;
 }
}
''')
    quote = lambda p: json.dumps(p.resolve().as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\n'
        'project(CardBusChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        f'add_executable(card_check check.cpp {quote(target/"periph.cpp")})\n'
        f'target_include_directories(card_check PRIVATE {quote(sdk/"runtime/include")})\n'
        'if(WIN32)\n target_link_libraries(card_check PRIVATE bcrypt)\nendif()\n')
    build = tmp_path/'build'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],
                    ['cmake','--build',str(build),'--config','Release','--parallel','2']):
        run = subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert run.returncode == 0,run.stdout+run.stderr
    executable = next(p for p in (build/'card_check',build/'Release/card_check.exe')if p.exists())
    run = subprocess.run([str(executable),str(tmp_path)],capture_output=True,text=True,timeout=20)
    assert run.returncode == 0,f'exit={run.returncode}\n'+run.stdout+run.stderr


def test_card_patch_requires_the_pinned_runtime_anchors(tmp_path):
    target = tmp_path/'runtime/periph/src'
    target.mkdir(parents=True)
    (target/'periph.cpp').write_text('unrecognized runtime')
    with pytest.raises(ValueError,match='Pinned retail cartridge integration differs'):
        patch(tmp_path)
