// SPDX-License-Identifier: MIT
#include <anygba/system.hpp>
#include <anygba/relocated.h>
#include <algorithm>
#include <cstring>

namespace anygba {
anygba_fn System::lookup_relocated(std::uint32_t address,bool thumb) const {
    if (!options_.relocated_entries || !options_.relocated_count || address%(thumb?2:4)) return nullptr;
    const auto region=address>>24;
    const auto* ram=region==2?&mem_.ewram:region==3?&mem_.iwram:nullptr;
    const unsigned width=thumb?2:4,offset=address&0x00ffffffu;
    if (!ram || std::uint64_t(offset)+width>ram->size()) return nullptr;
    std::uint32_t prefix=0;
    for(unsigned i=0;i<width;++i)prefix|=std::uint32_t((*ram)[offset+i])<<(i*8);
    const auto end=options_.relocated_entries+options_.relocated_count;
    auto it=std::lower_bound(options_.relocated_entries,end,prefix,
        [](const anygba_relocated_entry& entry,std::uint32_t value){return entry.prefix<value;});
    for(;it!=end && it->prefix==prefix;++it) {
        if ((it->thumb!=0)!=thumb || offset<it->offset || it->source<0x08000000) continue;
        const auto start=offset-it->offset,source=it->source-0x08000000;
        if (std::uint64_t(start)+it->size>ram->size() || std::uint64_t(source)+it->size>mem_.rom_size) continue;
        if(cpu_.rom_patched) {
            const auto patch=rom_patches_.lower_bound(it->source&~1u);
            if(patch!=rom_patches_.end() && patch->first<std::uint64_t(it->source)+it->size)continue;
        }
        if(std::memcmp(ram->data()+start,mem_.rom.data()+source,it->size)==0)return it->fn;
    }
    return nullptr;
}
}
