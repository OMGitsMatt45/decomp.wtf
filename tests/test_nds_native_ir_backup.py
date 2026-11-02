"""Original cartridge images exercise IR savedata framing and raw persistence."""
import json
from pathlib import Path
import shutil
import subprocess

from decompnet.nds_native.flash_ir import patch
from .test_nds_native import sdk  # noqa: F401


def test_native_ir_prefix_and_direct_chip_roundtrip(tmp_path,sdk):
    root=tmp_path/'r';target=root/'runtime/periph/src';target.mkdir(parents=True)
    shutil.copyfile(sdk/'runtime/periph/src/periph.cpp',target/'periph.cpp');patch(root)
    source=tmp_path/'check.cpp'
    source.write_text(r'''
#include <dsr/periph.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <cstdint>
std::vector<uint8_t> transfer(dsr::GameCard& card,std::vector<uint8_t> bytes){
 std::vector<uint8_t> result;
 for(unsigned i=0;i<bytes.size();++i){card.io_write(0x040001a0,0xa000|(i+1<bytes.size()?0x40:0),16);card.io_write(0x040001a2,bytes[i],8);result.push_back(uint8_t(card.io_read(0x040001a2,8)));}
 return result;
}
int main(int argc,char** argv){
 const std::filesystem::path folder=argv[1];
 for(bool infrared:{false,true}){
  const auto rom=folder/(infrared?"ir.nds":"plain.nds"),save=folder/(infrared?"ir.sav":"plain.sav");
  std::vector<uint8_t> header(512);header[12]=infrared?'I':'A';
  {std::ofstream file(rom,std::ios::binary);file.write(reinterpret_cast<char*>(header.data()),header.size());}
  {
   dsr::GameCard card(rom,save,dsr::BackupType::Flash512K);
   // IR firmware identification is independent of savedata commands and WEL.
   const auto version=transfer(card,{8,0,0});
   if(version.back()!=(infrared?0xaa:0xff))return 9;
   if(transfer(card,{8}).back()==0xaa)return 10;
   if(transfer(card,{0,8,0}).back()!=0xff)return 11;
   if(transfer(card,{0,5,0}).back()!=(infrared?0:255))return 1;
   auto command=[&](std::vector<uint8_t> bytes){if(infrared)bytes.insert(bytes.begin(),0);return transfer(card,bytes);};
   command({6});if((command({5,0}).back()&2)==0)return 2;
   if(transfer(card,{8,0}).back()!=(infrared?0xaa:0xff))return 12;
   if((command({5,0}).back()&2)==0)return 13;
   command({2,0,0x12,0x34,0x5a,0,0xa5});
   auto read=command({3,0,0x12,0x34,0,0,0});
   if(read[read.size()-3]!=0x5a||read[read.size()-2]!=0||read.back()!=0xa5)return 3;
   if((command({5,0}).back()&2)!=0)return 4;
   auto id=command({0x9f,0,0,0});if(id[id.size()-3]!=0x20||id.back()!=0x13)return 5;
   if(!card.flush_save())return 6;
  }
  if(std::filesystem::file_size(save)!=512*1024)return 7;
  dsr::GameCard reopened(rom,save,dsr::BackupType::Flash512K);
  auto bytes=infrared?std::vector<uint8_t>{0,3,0,0x12,0x34,0}:std::vector<uint8_t>{3,0,0x12,0x34,0};
  if(transfer(reopened,bytes).back()!=0x5a)return 8;
 }
}
''')
    quote=lambda p:json.dumps(p.resolve().as_posix())
    (tmp_path/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(IRChecks LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 20)\n'
        f'add_executable(ir_check check.cpp {quote(target/"periph.cpp")})\n'
        f'target_include_directories(ir_check PRIVATE {quote(sdk/"runtime/include")})\n'
        'if(WIN32)\ntarget_link_libraries(ir_check PRIVATE bcrypt)\nendif()\n')
    build=tmp_path/'b'
    for command in (['cmake','-S',str(tmp_path),'-B',str(build)],['cmake','--build',str(build),'--config','Release','--parallel','2']):
        done=subprocess.run(command,capture_output=True,text=True,timeout=120)
        assert done.returncode==0,done.stdout+done.stderr
    exe=next(p for p in(build/'ir_check',build/'Release/ir_check.exe')if p.exists())
    done=subprocess.run([str(exe),str(tmp_path)],capture_output=True,text=True,timeout=20)
    assert done.returncode==0,f'exit={done.returncode}\n'+done.stdout+done.stderr
