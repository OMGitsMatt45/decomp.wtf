// SPDX-License-Identifier: CC0-1.0
// Original protocol tests: no game assets or Nintendo BIOS.
#include "anygba/system.hpp"
#include "save/save.h"
#include <filesystem>
#include <iostream>
#include <vector>
#include <array>
#include <algorithm>

void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Clock {
    anygba::System& s;
    void data(unsigned v){s.write16(0x080000c4,uint16_t(v));}
    void start(){s.write16(0x080000c8,1);s.write16(0x080000c6,7);data(1);data(5);}
    void send(unsigned value){for(int i=7;i>=0;--i){unsigned bit=(value>>i)&1;data(4|(bit<<1));data(5|(bit<<1));}}
    std::vector<unsigned> read(unsigned command,unsigned count){
        start();send(command);s.write16(0x080000c6,5);std::vector<unsigned> result;
        for(unsigned n=0;n<count;++n){unsigned v=0;for(unsigned i=0;i<8;++i){data(4);data(5);v|=((s.read16(0x080000c4)>>1)&1)<<i;}result.push_back(v);}
        data(1);return result;
    }
};
void command(anygba::System& s,unsigned value){s.write8(0x0e005555,0xaa);s.write8(0x0e002aaa,0x55);s.write8(0x0e005555,uint8_t(value));}
int main(int argc,char** argv){try{
    require(argc==2,"provide a new test save path");std::filesystem::path file=argv[1];
    require(!std::filesystem::exists(file),"test save path must not exist");
    std::vector<uint8_t> rom(1024);const char* id="FLASH1M_V103";
    std::copy(id,id+11,rom.begin()+512);std::copy_n("BPEE",4,rom.begin()+0xac);
    anygba::Options options;options.log_misses=false;options.rtc_start=1101044730;
    auto system=std::make_unique<anygba::System>(rom,nullptr,options);auto& s=*system;
    anygba::save::SaveFile persistence(file,s.backup());
    require(s.backup().type()==anygba::save::Type::Flash128,"Flash128 detection");
    command(s,0x90);require(s.read8(0x0e000000)==0x62&&s.read8(0x0e000001)==0x13,"Flash128 ID");command(s,0xf0);
    command(s,0xa0);s.write8(0x0e001234,0x12);
    command(s,0xb0);s.write8(0x0e000000,1);require(s.read8(0x0e001234)==255,"separate flash banks");
    command(s,0xa0);s.write8(0x0e001234,0x56);
    require(s.backup().data().size()==131072,"Flash128 length");
    require(!persistence.flush(),"Flash128 atomic flush");
    auto loaded=std::make_unique<anygba::System>(rom,nullptr,options);
    {anygba::save::SaveFile save(file,loaded->backup());save.load();}
    require(loaded->backup().data()[0x1234]==0x12&&loaded->backup().data()[0x11234]==0x56,"Flash128 reload both banks");
    command(s,0xb0);s.write8(0x0e000000,0);command(s,0x80);
    s.write8(0x0e005555,0xaa);s.write8(0x0e002aaa,0x55);s.write8(0x0e001000,0x30);
    require(s.read8(0x0e001234)==255&&s.backup().data()[0x11234]==0x56,"sector erase respects bank");
    require(s.has_rtc(),"RTC detection");Clock clock{s};
    require(clock.read(0x63,1)==std::vector<unsigned>{0x40},"RTC 24-hour status");
    require(clock.read(0x65,7)==std::vector<unsigned>{0x04,0x11,0x21,0x00,0x13,0x45,0x30},"RTC BCD date/time");
    // Advance the actual scheduler over a second, rather than rereading a static fixture.
    s.memory().rom[0]=0xfe;s.memory().rom[1]=0xff;s.memory().rom[2]=0xff;s.memory().rom[3]=0xea;
    s.on_vblank=[](anygba::System& x){if(x.frames()==61)x.stop();};s.run();
    auto time=clock.read(0x67,3);require(time==std::vector<unsigned>{0x13,0x45,0x31},"RTC advances with emulated cycles");
    std::cout<<"Flash128 detection, IDs, banks, erase, atomic save/reload and RTC serial time/advance passed\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
