// SPDX-License-Identifier: CC0-1.0
#include "decomp_owned_write.hpp"
#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>

int main() {
    GSMem::InitLookupTables();
    constexpr uint32_t bytes=dq8::gfx::kGsVramBytes;
    std::vector<uint8_t> expected(bytes),actual(bytes),pixels(512u*128u*4u);
    uint32_t random=0x673aacd1u,cases=0;
    const auto next=[&](){random^=random<<13;random^=random>>17;random^=random<<5;return random;};
    for(auto &byte:pixels)byte=uint8_t(next());
    uint64_t referenceNs=0,batchedNs=0;
    for(uint32_t base: {0u,1u,7u,15u,31u,32u,63u,95u,16353u,16383u})
    for(uint32_t bw: {1u,2u,8u})
    for(uint32_t seed=0;seed<8u;++seed) {
        const uint32_t x0=(seed*11u)%65u,y0=seed*13u;
        const uint32_t x1=x0+13u+seed*61u,y1=y0+7u+seed*9u;
        dq8::gfx::GsPageSet owned;
        for(uint32_t p=0;p<dq8::gfx::kGsPageCount;++p)
            if(seed==0u || (seed!=1u && (next()&1u)))owned.set(p);
        std::fill(expected.begin(),expected.end(),0xa5u);actual=expected;
        auto started=std::chrono::steady_clock::now();
        for(uint32_t y=y0;y<y1;++y)for(uint32_t x=x0;x<x1;++x) {
            const uint32_t page=(GSPSMCT32::addrPSMCT32(base,bw,x,y)>>13u)%dq8::gfx::kGsPageCount;
            if(!owned.test(page))continue;
            uint32_t value;std::memcpy(&value,pixels.data()+((y-y0)*(x1-x0)+x-x0)*4u,4u);
            GSMem::WriteCT32(expected.data(),base,bw,x,y,value);
        }
        referenceNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count();
        started=std::chrono::steady_clock::now();
        decomp_ps2::graphics::writeOwnedCt32(actual.data(),base,bw,x0,y0,x1,y1,owned,pixels.data());
        batchedNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count();
        if(actual!=expected) {
            std::fprintf(stderr,"ownership mismatch: base=%u bw=%u seed=%u\n",base,bw,seed);return 1;
        }
        ++cases;
    }
    std::printf("{\"cases\":%u,\"full_vram_identical\":true,\"reference_ns\":%llu,\"batched_ns\":%llu}\n",cases,
        static_cast<unsigned long long>(referenceNs),static_cast<unsigned long long>(batchedNs));
}
