// SPDX-License-Identifier: MIT
#include "cheats.hpp"
#include "anygba/system.hpp"
#include <iostream>
#include <stdexcept>

using namespace anygba::cheats;
void check(bool condition,const char* message){if(!condition)throw std::runtime_error(message);}
Program program(Format format,std::initializer_list<const char*> lines){
    std::vector<std::string> owned(lines.begin(),lines.end());return compile(format,owned);
}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::runtime_error("provide a scratch directory");
    auto folder=std::filesystem::path(argv[1]);
    std::filesystem::create_directories(folder);
    anygba::Options options;options.log_misses=false;
    anygba::System system(std::vector<uint8_t>(0x400),nullptr,options);
    auto a=uint32_t{0xA86CDBA5},v=uint32_t{0x19BA49B3};gameshark_decrypt(a,v,true);
    check(a==0x45455042&&v==0x001DC0DE,"published Emerald Action Replay master decryption");
    run(program(Format::Auto,{"8791F574 20D9F121","A9873144 203A53CE"}),system,{});
    check(system.read16(0x020048e0)==9999,"published encrypted GameShark RAM write");
    run(program(Format::CodeBreaker,{"82000200 1234","32000202 0056"}),system,{});
    check(system.read32(0x02000200)==0x00561234,"CodeBreaker write widths and byte order");
    run(program(Format::CodeBreaker,{"72000200 1234","82000204 4567"}),system,{});
    check(system.read16(0x02000204)==0x4567,"CodeBreaker true conditional");
    run(program(Format::CodeBreaker,{"72000200 0000","82000204 9999"}),system,{});
    check(system.read16(0x02000204)==0x4567,"CodeBreaker false conditional");
    system.write32(0x03000010,0x02001000);system.write32(0x03000014,0x02002000);
    system.write32(0x020020ac,0xabcd4321);
    run(program(Format::Raw,{"[03000010]+0490:000F423F^[03000014]+00AC"}),system,{});
    check((system.read32(0x02001490)^0xabcd4321)==999999,"relocated and encrypted save-block write");
    system.write8(0x02001080,0x11);
    run(program(Format::Raw,{"[03000010]+0080|80"}),system,{});
    check(system.read8(0x02001080)==0x91,"flag operation preserves unrelated bits");
    check(gba_frontend::native_cheat_error(program(Format::Raw,{"08000100:4770"})).has_value(),"ROM patches rejected for native execution");
    gba_frontend::Cheats manager;manager.load(folder/"prefs.toml");
    CheatList draft;auto i=draft.add_custom("Persistent RAM code",Format::CodeBreaker,{"82000208 3456"});
    check(!draft.set_enabled(i,true),"enable stored code");
    check(!manager.commit(draft),"initial preference write");
    check(!manager.commit(draft),"atomic replacement of existing preference file");
    gba_frontend::Cheats reopened;reopened.load(folder/"prefs.toml");
    check(reopened.enabled()==1,"enabled preference survives process reload");
    reopened.apply(system,0,false);check(system.read16(0x02000208)==0x3456,"persisted cheat executes");
    auto disabled=reopened.list();check(!disabled.set_enabled(0,false),"disable stored cheat");
    check(!reopened.commit(disabled),"save disabled preference");
    gba_frontend::Cheats off;off.load(folder/"prefs.toml");system.write16(0x02000208,7);off.apply(system,0,false);
    check(off.enabled()==0&&system.read16(0x02000208)==7,"disabled preference stays inactive");
    std::cout<<"Cheat decryption, RAM operations, native policy and preferences passed\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
