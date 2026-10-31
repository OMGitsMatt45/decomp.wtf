// SPDX-License-Identifier: MIT
#include "cheats.hpp"
#include "cheat_catalog.hpp"
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
    run(program(Format::Auto,{"6266061B C8C9D80F"}),system,{});
    check(system.read16(0x020322e4)==1,"encrypted Action Replay EWRAM mirror autodetection");
    run(program(Format::Auto,{"0230FC00 00001234"}),system,{});
    check(system.read16(0x03007c00)==0x1234,"decrypted Action Replay IWRAM mirror autodetection");
    auto native=[](anygba_cpu* c){AG_ENTER(c,0x08000000u);c->r[0]++;c->r[15]=c->r[14]&~1u;};
    auto& cpu=system.cpu();cpu.t=1;cpu.r[14]=0x08000005;cpu.r[0]=10;
    system.set_native_entry_hook(0x08000000,true,[](anygba::System& s){s.cpu().r[0]=70;return false;});
    native(&cpu);check(cpu.r[0]==71,"native hook can adjust direct-call arguments and continue compiled code");
    system.set_native_entry_hook(0x08000000,true,[](anygba::System& s){auto& c=s.cpu();c.r[0]=77;c.r[15]=c.r[14]&~1u;return true;});
    native(&cpu);check(cpu.r[0]==77&&cpu.r[15]==0x08000004,"native hook can replace direct compiled calls without interpreting");
    system.reset();cpu.t=1;cpu.r[14]=0x08000005;
    check(cpu.native_hooks,"active native hook survives reset");native(&cpu);check(cpu.r[0]==77,"native hook runs after reset");
    system.set_native_entry_hook(0x08000000,true,{});native(&cpu);check(cpu.r[0]==78&&!cpu.native_hooks,"removing native hook restores original code");
    std::vector<gba_frontend::CheatPreset> presets{
        {"first","First","Items","slot","","",Format::Raw,{"02000220:1234"}},
        {"second","Second","Items","slot","","",Format::Raw,{"02000220:5678"}},
        {"bad","Unsupported","Other","","","",Format::Raw,{"08000100:4770"}}};
    gba_frontend::CheatCatalog catalog;catalog.configure(presets);catalog.load(folder/"catalog.sav");
    check(!catalog.all_off(),"initial catalog preference write");
    system.write16(0x02000220,9);catalog.apply(system,0,false);check(system.read16(0x02000220)==9,"catalog defaults to no writes");
    check(!catalog.set_enabled("first",true),"catalog toggle persists");catalog.apply(system,0,false);check(system.read16(0x02000220)==0x1234,"catalog preset takes effect");
    check(!catalog.set_enabled("second",true)&&!catalog.enabled("first"),"exclusive presets cannot conflict");
    gba_frontend::CheatCatalog restored;restored.configure(presets);restored.load(folder/"catalog.sav");
    check(restored.enabled("second")&&!restored.enabled("first"),"catalog selections survive process reload");
    check(restored.set_enabled("bad",true).has_value()&&!restored.enabled("bad"),"unsupported catalog code cannot become silently active");
    check(!restored.all_off(),"catalog all-off persists");system.write16(0x02000220,9);restored.apply(system,0,false);check(system.read16(0x02000220)==9,"all-off stops future writes");
    gba_frontend::CheatCatalog no_path;no_path.configure(presets);check(no_path.set_enabled("first",true).has_value()&&!no_path.enabled("first"),"failed persistence rolls back toggle");
    std::cout<<"Cheat decryption, RAM operations, native policy and preferences passed\nNative direct-call hooks, mirrored codes and preset persistence passed\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
