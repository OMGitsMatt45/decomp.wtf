// SPDX-License-Identifier: CC0-1.0
// Original edge and random inputs; compare with the pinned arithmetic engine.
#include "ps2_vu1_program.h"
#include <cfenv>
#include <cstdio>
#include <cstdlib>

using namespace ps2_vu_program;
constexpr uint32_t instruction(uint32_t code,bool special) {
    return (15u<<21u)|(2u<<16u)|(1u<<11u)|(special?((code&0x7cu)<<4u)|0x3cu|(code&3u):(3u<<6u)|code);
}
uint64_t cases=0;
uint32_t randomWord(){static uint32_t state=0x31c4076bu;state=state*1664525u+1013904223u;return state;}
template<uint32_t Upper> bool check(VU1State &state) {
    const UpperInputs inputs{state.vf[1],state.vf[2],state.acc,state.i,state.q};
    UpperSink expected{};float actual[4];
    ps2_vu_detail::upper::computeUpper(Upper,inputs,expected);
    const uint32_t clip=sse_plain::run<Upper>(state,actual);++cases;
    if(expected.hasClip)return clip==expected.clipBits;
    return !std::memcmp(actual,expected.value,sizeof(actual));
}
template<uint32_t... Codes>bool checkSpecial(VU1State &state,std::integer_sequence<uint32_t,Codes...>){return (check<instruction(Codes,true)>(state)&&...);}
template<uint32_t... Codes>bool checkNormal(VU1State &state,std::integer_sequence<uint32_t,Codes...>){return (check<instruction(Codes,false)>(state)&&...);}
int main() {
    VU1State state{};
    constexpr uint32_t edges[]={0,0x80000000u,1,0x807fffffu,0x00800000u,0x80800000u,0x3f800000u,0xbf800000u,0x4effffffu,0x4f000000u,0xcf000000u,0xcf000001u,0x7f7fffffu,0xff7fffffu,0x7f800000u,0xff800000u,0x7fc01234u,0xff801234u,0x7fffffffu,0xffffffffu,
        0x4cffffffu,0x4d000000u,0x4d000001u,0xccffffffu,0xcd000000u,0xcd000001u,
        0x48ffffffu,0x49000000u,0x49000001u,0xc8ffffffu,0xc9000000u,0xc9000001u,
        0x477fffffu,0x47800000u,0x47800001u,0xc77fffffu,0xc7800000u,0xc7800001u,
        0x80000001u,0x7ffffffeu,0x01000001u,0xfeffffffu};
    constexpr uint32_t count=uint32_t(std::size(edges));
    for(int rounding:{FE_TONEAREST,FE_TOWARDZERO,FE_UPWARD,FE_DOWNWARD}) {
        if(std::fesetround(rounding))return 2;
        for(uint32_t index=0;index<100000u;++index) {
            for(uint32_t reg=1;reg<=2;++reg)for(uint32_t lane=0;lane<4;++lane) {
                // Cartesian edges include equal values, opposite signed zero,
                // and neighbours of every scaled FTOI saturation threshold.
                const uint32_t bits=index<count*count?edges[((reg==1?index/count:index%count)+lane)%count]:randomWord();
                std::memcpy(&state.vf[reg][lane],&bits,4);
            }
            const uint32_t i=index<count*count?edges[index%count]:randomWord();std::memcpy(&state.i,&i,4);
            if(!checkSpecial(state,std::integer_sequence<uint32_t,0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17,0x1d,0x1f>{})||
               !checkNormal(state,std::integer_sequence<uint32_t,0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17,0x1d,0x1f,0x2b,0x2f>{})) {
                std::fprintf(stderr,"SSE mismatch rounding=%d input=%u\n",rounding,index);return 1;
            }
        }
    }
    std::printf("{\"cases\":%llu,\"rounding_modes\":4,\"bit_identical\":true}\n",static_cast<unsigned long long>(cases));
}
