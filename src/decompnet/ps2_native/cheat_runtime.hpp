// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
namespace decomp_ps2_cheats {
struct Write {uint32_t address,value,width;};
struct Selector {uint32_t group,bit;};
struct Entry {
    std::string id,name,group;
    std::vector<Write> data;
    std::vector<Selector> selectors;
    std::vector<Write> writes;
    bool enabled=false;
};
inline std::mutex selection_mutex;
inline std::atomic<uint64_t> selection_revision{1};
inline std::atomic<uint64_t> applications{0},menu_openings{0};
inline bool conflicts(const Entry &a,const Entry &b){
    for(const auto &left:a.writes)for(const auto &right:b.writes)
        for(uint32_t n=0;n<left.width;++n)for(uint32_t m=0;m<right.width;++m)
            if(left.address+n==right.address+m&&uint8_t(left.value>>(8*n))!=uint8_t(right.value>>(8*m)))return true;
    return false;
}
inline void toggle_entry(std::vector<Entry>& entries,std::atomic<uint32_t>* masks,size_t groups,size_t index){
    std::lock_guard lock(selection_mutex);
    if(index>=entries.size())throw std::out_of_range("PS2 cheat index");
    auto &entry=entries[index];entry.enabled=!entry.enabled;
    if(entry.enabled)for(size_t n=0;n<entries.size();++n)
        if(n!=index&&entries[n].enabled&&conflicts(entry,entries[n]))entries[n].enabled=false;
    std::vector<uint32_t> next(groups);
    for(const auto &e:entries)if(e.enabled)for(const auto &s:e.selectors){
        if(s.group>=groups)throw std::logic_error("PS2 cheat selector bound");
        next[s.group]|=s.bit;
    }
    for(size_t n=0;n<groups;++n)masks[n].store(next[n],std::memory_order_release);
    selection_revision.fetch_add(1,std::memory_order_release);
}
// Called by compiled EE functions, never by the presentation thread. Guest
// instructions remain byte-identical; selection only chooses compiled bodies.
inline void poll_entries(std::vector<Entry>& entries,uint8_t* ram){
    thread_local unsigned countdown=0;
    if(countdown++%256)return;
    thread_local uint64_t revision=0;
    thread_local std::vector<Write> active;
    const auto current=selection_revision.load(std::memory_order_acquire);
    if(revision!=current){
        std::lock_guard lock(selection_mutex);active.clear();
        for(const auto &entry:entries)if(entry.enabled)active.insert(active.end(),entry.data.begin(),entry.data.end());
        revision=current;
    }
    if(!ram)return;
    for(const auto &write:active){
        if(write.address>0x02000000u-write.width)throw std::out_of_range("PS2 cheat RAM bound");
        std::memcpy(ram+write.address,&write.value,write.width);
    }
    if(!active.empty())applications.fetch_add(1,std::memory_order_relaxed);
}
}
