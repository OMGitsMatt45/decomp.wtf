// SPDX-License-Identifier: CC0-1.0
// Original protocol tests: no game assets or Nintendo BIOS.
#include "anygba/system.hpp"
#include "save/save.h"
#include "ram_feedback.hpp"
#include "native_idle.hpp"
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
    bool repeated=false;
    void send(unsigned value){for(int i=7;i>=0;--i){unsigned bit=(value>>i)&1;data(4|(bit<<1));data(5|(bit<<1));if(repeated)data(5|(bit<<1));}}
    std::vector<unsigned> read(unsigned command,unsigned count){
        start();send(command);s.write16(0x080000c6,5);std::vector<unsigned> result;
        for(unsigned n=0;n<count;++n){unsigned v=0;for(unsigned i=0;i<8;++i){data(4);data(5);if(repeated)data(5);v|=((s.read16(0x080000c4)>>1)&1)<<i;}result.push_back(v);}
        data(1);return result;
    }
};
void command(anygba::System& s,unsigned value){s.write8(0x0e005555,0xaa);s.write8(0x0e002aaa,0x55);s.write8(0x0e005555,uint8_t(value));}
void advance(anygba::System& s,unsigned cycles){s.cpu().cycles-=int(cycles);s.tick();}
void timers(const std::vector<uint8_t>& rom){
    for(unsigned mode=0;mode<4;++mode){
        anygba::Options options;options.log_misses=false;
        auto system=std::make_unique<anygba::System>(rom,nullptr,options);auto& s=*system;
        const unsigned divisor=std::array<unsigned,4>{1,64,256,1024}[mode];
        s.write16(0x04000100,0xfffc);s.write16(0x04000102,uint16_t(0xc0|mode));
        advance(s,divisor*4-1);
        require(s.read16(0x04000100)==0xffff&&!(s.read16(0x04000202)&8),"timer prescaler boundary before overflow");
        advance(s,1);
        require(s.read16(0x04000100)==0xfffc&&(s.read16(0x04000202)&8),"timer exact reload and IRQ boundary");
        s.write16(0x04000202,8);require(!(s.read16(0x04000202)&8),"timer IRQ acknowledgement");
        advance(s,divisor*8);require(s.read16(0x04000100)==0xfffc,"timer repeated overflows do not drift");
        s.write16(0x04000102,0);auto held=s.read16(0x04000100);advance(s,99);
        require(s.read16(0x04000100)==held,"disabled timer stops");
    }
    anygba::Options options;options.log_misses=false;
    auto system=std::make_unique<anygba::System>(rom,nullptr,options);auto& s=*system;
    for(unsigned i=0;i<4;++i)s.write8(0x03000000+i,rom[512+i]);
    require(anygba_ram_variant_valid(&s.cpu(),0x03000000,0x03000004,0x08000200),"RAM variant guard accepts its exact ROM-backed body");
    require(!anygba_ram_variant_valid(&s.cpu(),0x03000000,0x03000004,0x08000201),"RAM variant guard rejects a different body at the same address");
    require(!anygba_ram_variant_valid(&s.cpu(),0x03000000,0x03000004,0),"RAM variant guard cannot reuse another variant's validity");
    s.write16(0x04000108,10);s.write16(0x0400010a,0x84);
    s.write16(0x04000104,0xfffe);s.write16(0x04000106,0xc4);
    s.write16(0x04000100,0xfff0);s.write16(0x04000102,0xc0);
    advance(s,32);
    require(s.read16(0x04000100)==0xfff0&&s.read16(0x04000104)==0xfffe&&s.read16(0x04000108)==11,"three-timer cascade reloads on the exact parent overflow");
    require((s.read16(0x04000202)&0x18)==0x18,"cascaded timers raise independent interrupt flags");
}
int main(int argc,char** argv){try{
    const std::array<uint8_t,4> leaf{0x00,0x78,0x70,0x47};
    std::vector<uint8_t> sample_rom(64,0xcc),stack(32,0x55);
    std::copy(leaf.begin(),leaf.end(),sample_rom.begin()+1); // unaligned match must be skipped
    std::copy(leaf.begin(),leaf.end(),sample_rom.begin()+16);
    std::copy(leaf.begin(),leaf.end(),stack.begin());
    auto match=gba_feedback::source(sample_rom,stack,true);
    require(match&&match->address==0x08000010&&match->size==4,"bounded RAM leaf signature ignores live stack tail");
    require(!gba_feedback::leaf_size(std::array<uint8_t,4>{0x00,0x48,0x70,0x47},true),"PC-relative leaf cannot use short matching");
    require(!gba_feedback::leaf_size(std::array<uint8_t,4>{0x00,0xe0,0x70,0x47},true),"branching leaf cannot use short matching");
    require(!gba_feedback::leaf_size(std::array<uint8_t,4>{0x00,0x60,0x70,0x47},true),"writing leaf cannot use short matching");
    require(!gba_feedback::leaf_size(stack,false),"Thumb matching must not guess ARM code");
    require(argc==2,"provide a new test save path");std::filesystem::path file=argv[1];
    require(!std::filesystem::exists(file),"test save path must not exist");
    std::vector<uint8_t> rom(1024);const char* id="FLASH1M_V103";
    std::copy(id,id+11,rom.begin()+512);std::copy_n("BPEE",4,rom.begin()+0xac);
    timers(rom);
    const auto program=original_idle_game(uint32_t(rom.size()));
    anygba::Options options;options.log_misses=false;options.rtc_start=1101044730;
    auto system=std::make_unique<anygba::System>(rom,&program,options);auto& s=*system;
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
    clock.repeated=true;
    require(clock.read(0x65,7)==std::vector<unsigned>{0x04,0x11,0x21,0x00,0x13,0x45,0x30},"RTC repeated high GPIO writes cannot clock extra bits");
    // Abort in the middle of a byte with CS low and SCK low, then start afresh.
    clock.start();clock.data(4);clock.data(5);clock.data(0);clock.repeated=false;
    require(clock.read(0x63,1)==std::vector<unsigned>{0x40},"RTC recovers from a low-clock transfer abort");
    // Advance the actual scheduler over a second, rather than rereading a static fixture.
    s.memory().rom[0]=0xfe;s.memory().rom[1]=0xff;s.memory().rom[2]=0xff;s.memory().rom[3]=0xea;
    s.on_vblank=[](anygba::System& x){if(x.frames()==61)x.stop();};s.run();
    auto time=clock.read(0x67,3);require(time==std::vector<unsigned>{0x13,0x45,0x31},"RTC advances with emulated cycles");
    const std::array<int64_t,3> epochs{1078012799,1078099199,1104537599};
    const std::array<std::vector<unsigned>,3> dates{{{4,2,0x29,0,0,0,0},{4,3,1,1,0,0,0},{5,1,1,6,0,0,0}}};
    for(unsigned i=0;i<epochs.size();++i){
        options.rtc_start=epochs[i];auto rollover=std::make_unique<anygba::System>(rom,&program,options);
        rollover->memory().rom[0]=0xfe;rollover->memory().rom[1]=0xff;rollover->memory().rom[2]=0xff;rollover->memory().rom[3]=0xea;
        rollover->on_vblank=[](anygba::System& x){if(x.frames()==61)x.stop();};rollover->run();Clock edge{*rollover};
        require(edge.read(0x65,7)==dates[i],"RTC midnight, leap day, month and year rollover");
    }
    std::cout<<"Flash128 detection, IDs, banks, erase, atomic save/reload and RTC serial time/advance passed; timer prescalers, IRQs, cascades and calendar boundaries passed\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
