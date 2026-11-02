#pragma once
#include <cstdint>
#include <string>
#include <vector>

extern "C" uint32_t psx_read_word(uint32_t);
extern "C" void psx_write_byte(uint32_t,uint8_t);
extern "C" int psx_mod_game_started(void);

namespace ps1_host {
struct CheatWrite {
    uint32_t address,value,condition_address,condition_value,match;
    unsigned width;
    bool conditional,matching,restore,code;
    uint32_t original=0;
    bool owned=false;
};
struct Cheat {
    std::string name,description,group;
    std::vector<CheatWrite> writes;
    bool enabled=false;
    uint64_t applications=0,changes=0;
};
#include "cheat_catalog.inc"
inline uint64_t cheat_menu_openings=0,cheat_toggles=0;
inline uint32_t cheat_read(uint32_t address,unsigned width) {
    uint32_t value=0;
    for(unsigned i=0;i<width;++i) {
        const uint32_t at=address+i;
        value|=((psx_read_word(0x80000000u|(at&~3u))>>((at&3u)*8))&255u)<<(i*8);
    }
    return value;
}
inline void cheat_write(uint32_t address,unsigned width,uint32_t value) {
    for(unsigned i=0;i<width;++i)psx_write_byte(0x80000000u|address+i,(uint8_t)(value>>(i*8)));
}
inline void cheat_disable(size_t index) {
    auto &entry=cheats.at(index);
    for(auto &op:entry.writes) {
        if((op.restore||op.code)&&op.owned&&cheat_read(op.address,op.width)==op.value)
            cheat_write(op.address,op.width,op.restore?op.match:op.original);
        op.owned=false;
    }
    entry.enabled=false;
}
inline void cheat_set(size_t index,bool enabled) {
    if(index>=cheats.size())return;
    auto &entry=cheats[index];
    if(entry.enabled==enabled)return;
    if(enabled&&!entry.group.empty())
        for(size_t other=0;other<cheats.size();++other)
            if(other!=index&&cheats[other].enabled&&cheats[other].group==entry.group)cheat_disable(other);
    if(!enabled)cheat_disable(index);else entry.enabled=true;
    ++cheat_toggles;
}
inline void cheat_tick() {
    if(!psx_mod_game_started())return;
    for(auto &entry:cheats)if(entry.enabled) {
        ++entry.applications;
        for(auto &op:entry.writes) {
            if(op.conditional&&cheat_read(op.condition_address,2)!=op.condition_value)continue;
            const auto before=cheat_read(op.address,op.width);
            if(op.matching&&before!=op.match)continue;
            if(before==op.value)continue;
            op.original=before;op.owned=true;
            cheat_write(op.address,op.width,op.value);++entry.changes;
        }
    }
}
}
