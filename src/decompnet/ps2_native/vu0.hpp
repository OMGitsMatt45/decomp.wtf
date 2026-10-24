// SPDX-License-Identifier: MIT
// Static VU0 arithmetic uses the pinned runtime's shared VU arithmetic engine.
// The engine retains its GPL-3.0 license in the source-shipped runtime.
#pragma once
#include "ps2_runtime.h"
#include "ps2_vu1_upper_engine.h"
#include <cfenv>
#include <cstring>
#include <stdexcept>

namespace decomp_ps2 {
template<uint32_t Word> inline void vu_upper(R5900Context &ctx) {
    // VF0 is a hardwired vector, independent of a host context's zero-fill.
    ctx.vu0_vf[0]=_mm_set_ps(1.0f,0.0f,0.0f,0.0f);
    constexpr unsigned fs = (Word >> 11) & 31, ft = (Word >> 16) & 31;
    float left[4], right[4], accumulator[4];
    std::memcpy(left, &ctx.vu0_vf[fs], 16);
    std::memcpy(right, &ctx.vu0_vf[ft], 16);
    std::memcpy(accumulator, &ctx.vu0_acc, 16);
    if constexpr (fs == 0) { left[0]=left[1]=left[2]=0; left[3]=1; }
    if constexpr (ft == 0) { right[0]=right[1]=right[2]=0; right[3]=1; }
    struct Inputs {
        const float *left, *right, *accumulator; float scalar_i, scalar_q;
        float fs(unsigned n) const { return left[n]; }
        float ft(unsigned n) const { return right[n]; }
        float acc(unsigned n) const { return accumulator[n]; }
        float i() const { return scalar_i; }
        float q() const { return scalar_q; }
        bool compiledFastPath() const { return true; }
    } inputs{left,right,accumulator,ctx.vu0_i,ctx.vu0_q};
    struct Sink {
        R5900Context &ctx;
        void vf(unsigned reg, unsigned mask, const float *result) {
            if (!reg) return;
            float value[4]; std::memcpy(value, &ctx.vu0_vf[reg], 16);
            for (unsigned n=0;n<4;n++) if(mask & (8u >> n)) value[n]=result[n];
            std::memcpy(&ctx.vu0_vf[reg], value, 16);
        }
        void acc(unsigned mask, const float *result) {
            float value[4]; std::memcpy(value,&ctx.vu0_acc,16);
            for (unsigned n=0;n<4;n++) if(mask & (8u >> n)) value[n]=result[n];
            std::memcpy(&ctx.vu0_acc,value,16);
        }
        void fmac(uint32_t mac, uint32_t status, uint32_t sticky) {
            ctx.vu0_mac_flags=mac & 0xffffu;
            ctx.vu0_status=static_cast<uint16_t>((ctx.vu0_status & ~0xfu) |
                (status & 0xfu) | (((status | sticky) & 0xfu) << 6));
        }
        void clip(uint32_t bits) { ctx.vu0_clip_flags=((ctx.vu0_clip_flags << 6) | bits) & 0xffffffu; }
        void reserved(uint32_t) { throw std::runtime_error("unsupported static VU0 operation"); }
    } sink{ctx};
    struct Rounding {
        int previous=std::fegetround();
        Rounding() { std::fesetround(FE_TOWARDZERO); }
        ~Rounding() { std::fesetround(previous); }
    } rounding;
    // Word is fixed in generated C++; there is no instruction fetch, guest
    // interpreter dispatch or runtime compilation on this path.
    ps2_vu_detail::upper::computeUpper(Word,inputs,sink);
}
}
