// SPDX-License-Identifier: MIT
#pragma once
#include <algorithm>
#include <cstdint>
#include <optional>
#include <span>

namespace gba_feedback {
struct Source { uint32_t address, size; };

// Short Thumb leaf helpers can live on a stack beside changing caller data.
// Recognize only low-register arithmetic and reads with no branches, writes,
// PC-relative operands, stack changes or calls, followed by BX LR. Ambiguous code keeps the
// existing 32-byte signature or stays interpreted.
inline unsigned leaf_size(std::span<const uint8_t> ram, bool thumb) {
    if (!thumb) return 0;
    for (unsigned at=0; at+2<=ram.size() && at<16; at+=2) {
        const unsigned op=ram[at]|unsigned(ram[at+1])<<8;
        if (op==0x4770) return at ? at+2 : 0;
        if ((op&0xe000)==0x0000 || (op&0xe000)==0x2000 || (op&0xfc00)==0x4000 ||
            ((op&0xf000)==0x5000 && ((op&0x0800) || (op&0x0e00)==0x0600)) ||
            (op&0xe800)==0x6800 || (op&0xf800)==0x8800) continue;
        return 0;
    }
    return 0;
}

inline std::optional<Source> source(std::span<const uint8_t> rom,
                                    std::span<const uint8_t> ram, bool thumb) {
    const auto find=[&](unsigned length, unsigned bound)->std::optional<Source> {
        if (!length || ram.size()<length) return {};
        auto begin=rom.begin();
        while (begin!=rom.end()) {
            auto hit=std::search(begin,rom.end(),ram.begin(),ram.begin()+length);
            if (hit==rom.end()) break;
            const auto offset=uint32_t(hit-rom.begin());
            if (offset%(thumb?2:4)==0) return Source{0x08000000u+offset,bound};
            begin=hit+1;
        }
        return {};
    };
    if (auto length=leaf_size(ram,thumb)) if (auto hit=find(length,length)) return hit;
    return find(unsigned(std::min<std::size_t>(32,ram.size())),0);
}
}
