// SPDX-License-Identifier: MIT
// Static VU0 arithmetic uses the pinned runtime's shared VU arithmetic engine.
// The engine retains its GPL-3.0 license in the source-shipped runtime.
#pragma once
#ifndef DECOMP_PS2_VU0_HPP
#define DECOMP_PS2_VU0_HPP
#include "ps2_runtime.h"
#include "ps2_vu1_upper_engine.h"
#include <cfenv>
#include <cstring>
#include <cstdlib>
#include <stdexcept>

namespace decomp_ps2 {
namespace vu0_detail {
    // Shared types instantiate the arithmetic engine once per translation
    // unit, rather than once for every register/opcode word in a retail corpus.
    struct Inputs {
        const float *left, *right, *accumulator; float scalar_i, scalar_q;
        float fs(unsigned n) const { return left[n]; }
        float ft(unsigned n) const { return right[n]; }
        float acc(unsigned n) const { return accumulator[n]; }
        float i() const { return scalar_i; }
        float q() const { return scalar_q; }
        bool compiledFastPath() const { return true; }
    };
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
    };
#if defined(_WIN64) && (defined(_M_X64) || defined(__x86_64__))
    PS2_VU_FORCE_INLINE __m128 normalizedLanes(__m128 value)
    {
        const auto bits = _mm_castps_si128(value);
        const auto sign = _mm_and_si128(bits, _mm_set1_epi32(INT32_MIN));
        const auto exponent = _mm_and_si128(bits, _mm_set1_epi32(0x7f800000));
        const auto zero = _mm_cmpeq_epi32(exponent, _mm_setzero_si128());
        const auto special = _mm_cmpeq_epi32(exponent, _mm_set1_epi32(0x7f800000));
        const auto normal = _mm_andnot_si128(_mm_or_si128(zero, special), bits);
        return _mm_castsi128_ps(_mm_or_si128(normal, _mm_or_si128(_mm_and_si128(zero, sign),
            _mm_and_si128(special, _mm_or_si128(sign, _mm_set1_epi32(0x7f7fffff))))));
    }

    constexpr uint8_t packedLaneMask[16] = {0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15};

    template<unsigned Lane>
    PS2_VU_FORCE_INLINE __m128 broadcastLane(__m128 lanes)
    {
        return _mm_shuffle_ps(lanes, lanes, _MM_SHUFFLE(Lane, Lane, Lane, Lane));
    }

    template<unsigned Destination>
    PS2_VU_FORCE_INLINE void storePackedLanes(__m128 &target, __m128 result)
    {
        if constexpr (Destination == 15u)
            target = result;
        else if constexpr (Destination != 0u)
            target = _mm_blend_ps(target, result, packedLaneMask[Destination]);
    }

    constexpr bool isMinMax(uint32_t word)
    {
        const auto op = word & 0x3fu;
        return (op >= 0x10u && op <= 0x17u) || op == 0x1du || op == 0x1fu ||
               op == 0x2bu || op == 0x2fu;
    }

    template <uint32_t Word>
    PS2_VU_FORCE_INLINE void selectMinMax(R5900Context &ctx)
    {
        constexpr unsigned op = Word & 0x3fu, dest = (Word >> 21u) & 15u;
        constexpr unsigned fs = (Word >> 11u) & 31u, ft = (Word >> 16u) & 31u, fd = (Word >> 6u) & 31u;
        if constexpr (fd != 0u && dest != 0u)
        {
            const auto left = normalizedLanes(ctx.vu0_vf[fs]);
            __m128 right;
            if constexpr (op <= 0x17u)
            {
                constexpr unsigned component = op & 3u;
                const auto lanes = ctx.vu0_vf[ft];
                right = _mm_shuffle_ps(lanes, lanes, _MM_SHUFFLE(component, component, component, component));
            }
            else if constexpr (op == 0x1du || op == 0x1fu)
                right = _mm_set1_ps(ctx.vu0_i);
            else
                right = ctx.vu0_vf[ft];
            right = normalizedLanes(right);

            // Normalization leaves finite normals and signed zeros. SSE
            // selects the second operand on ties, preserving its zero sign.
            constexpr bool maximum = op <= 0x13u || op == 0x1du || op == 0x2bu;
            const auto result = maximum ? _mm_max_ps(left, right) : _mm_min_ps(left, right);
            if constexpr (dest == 15u)
                ctx.vu0_vf[fd] = result;
            else
            {
                constexpr uint8_t reverse[16] = {0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15};
                ctx.vu0_vf[fd] = _mm_blend_ps(ctx.vu0_vf[fd], result, reverse[dest]);
            }
        }
    }

    template <uint32_t Word>
    PS2_VU_FORCE_INLINE bool tryBroadcastMadd(const Inputs &in, Sink &sink)
    {
        constexpr bool accumulator = (Word & 0x3fu) >= 0x3cu;
        constexpr uint32_t op = accumulator ? (Word & 3u) | ((Word >> 4u) & 0x7cu) : Word & 0x3fu;
        constexpr uint32_t dest = (Word >> 21u) & 15u;
        if constexpr (op < 0x08u || op > 0x0bu || dest == 0u)
            return false;
        else
        {
            // Use the same conservative exponent bounds as the VU1 product-sum
            // path. Ambiguous products and results go through the exact engine.
            const auto left = normalizedLanes(_mm_loadu_ps(in.left));
            const auto right = normalizedLanes(_mm_set1_ps(in.ft(op & 3u)));
            const auto acc = normalizedLanes(_mm_loadu_ps(in.accumulator));
            const auto product = _mm_mul_ps(left, right);
            const auto result = _mm_add_ps(acc, product);
            const auto none = _mm_setzero_si128();
            const auto magnitude = _mm_set1_epi32(0x7fffffff);
            const auto exponent = [](__m128 lanes) PS2_VU_INLINE_LAMBDA {
                return _mm_and_si128(_mm_srli_epi32(_mm_castps_si128(lanes), 23), _mm_set1_epi32(255));
            };
            const auto leftExp = exponent(left);
            const auto rightExp = exponent(right);
            const auto resultExp = exponent(result);
            const auto productBound = _mm_add_epi32(leftExp, rightExp);
            const auto zeroProduct = _mm_or_si128(_mm_cmpeq_epi32(leftExp, none), _mm_cmpeq_epi32(rightExp, none));
            const auto risky = _mm_andnot_si128(zeroProduct,
                _mm_or_si128(_mm_cmpgt_epi32(productBound, _mm_set1_epi32(379)),
                             _mm_cmpgt_epi32(productBound, _mm_add_epi32(resultExp, _mm_set1_epi32(146)))));
            const auto normal = _mm_and_si128(_mm_cmpgt_epi32(resultExp, _mm_set1_epi32(1)),
                                               _mm_cmplt_epi32(resultExp, _mm_set1_epi32(254)));
            const auto zero = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(result), magnitude), none);
            const auto safe = _mm_or_si128(_mm_andnot_si128(risky, normal), _mm_and_si128(zero, zeroProduct));
            const auto mask = [](__m128i lanes) PS2_VU_INLINE_LAMBDA { return _mm_movemask_ps(_mm_castsi128_ps(lanes)); };
            constexpr uint8_t reverse[16] = {0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15};
            constexpr int active = reverse[dest];
            if ((mask(safe) & active) != active)
                return false;

            const auto tiny = _mm_cmplt_epi32(_mm_and_si128(_mm_castps_si128(product), magnitude), _mm_set1_epi32(0x00800000));
            const uint32_t sticky = ((mask(tiny) & active) ? 1u : 0u) |
                ((_mm_movemask_ps(_mm_xor_ps(left, right)) & active) ? 2u : 0u) |
                ((mask(_mm_andnot_si128(zeroProduct, tiny)) & active) ? 4u : 0u);
            const uint32_t zeros = reverse[mask(zero) & active];
            const uint32_t signs = reverse[_mm_movemask_ps(result) & active];
            const uint32_t current = (zeros != 0u) | ((signs != 0u) << 1u);
            float values[4];
            _mm_storeu_ps(values, result);
            sink.fmac(zeros | (signs << 4u), current, sticky);
            if constexpr (accumulator)
                sink.acc(dest, values);
            else
                sink.vf((Word >> 6u) & 31u, dest, values);
            return true;
        }
    }

    // This engine uses float and double SSE arithmetic on Windows x64.
    // Keep the host exception flags raised by the instruction.
    struct Rounding {
        static constexpr unsigned mask = _MM_ROUND_MASK;
        static constexpr unsigned towardZero = _MM_ROUND_TOWARD_ZERO;
        unsigned previous;
        Rounding() {
            const unsigned control = _mm_getcsr();
            previous = control & mask;
            if (previous != towardZero)
                _mm_setcsr((control & ~mask) | towardZero);
        }
        ~Rounding() {
            if (previous != towardZero)
                _mm_setcsr((_mm_getcsr() & ~mask) | previous);
        }
    };

    template <uint32_t Word>
    constexpr bool packedAddSubWord()
    {
        constexpr unsigned low = Word & 0x3fu;
        constexpr unsigned op = low >= 0x3cu ? (Word & 3u) | ((Word >> 4u) & 0x7cu) : low;
        return (Word & 0x01e00000u) != 0u &&
            (op <= 7u || op == 0x20u || op == 0x22u || op == 0x24u || op == 0x26u || op == 0x28u || op == 0x2cu);
    }

    template <uint32_t Word>
    PS2_VU_FORCE_INLINE bool tryPackedAddSub(R5900Context &ctx)
    {
        constexpr unsigned low = Word & 0x3fu;
        constexpr bool accumulator = low >= 0x3cu;
        constexpr unsigned op = accumulator ? (Word & 3u) | ((Word >> 4u) & 0x7cu) : low;
        constexpr unsigned destination = (Word >> 21u) & 15u;
        constexpr bool add = op <= 3u || op == 0x20u || op == 0x22u || op == 0x28u;
        constexpr bool sub = (op >= 4u && op <= 7u) || op == 0x24u || op == 0x26u || op == 0x2cu;
        static_assert((add || sub) && destination != 0u);

        // Preserve the reference's trap order when a host exception is unmasked.
        if ((_mm_getcsr() & 0x1f80u) != 0x1f80u)
            return false;

        constexpr unsigned fs = (Word >> 11u) & 31u;
        constexpr unsigned ft = (Word >> 16u) & 31u;
        constexpr unsigned fd = (Word >> 6u) & 31u;
        const __m128 left = normalizedLanes(ctx.vu0_vf[fs]);
        __m128 right;
        if constexpr (op <= 7u)
            right = broadcastLane<op & 3u>(ctx.vu0_vf[ft]);
        else if constexpr (op == 0x20u || op == 0x24u)
            right = _mm_set1_ps(ctx.vu0_q);
        else if constexpr (op == 0x22u || op == 0x26u)
            right = _mm_set1_ps(ctx.vu0_i);
        else
            right = ctx.vu0_vf[ft];
        right = normalizedLanes(right);

        Rounding rounding;
        const __m128 result = add ? _mm_add_ps(left, right) : _mm_sub_ps(left, right);
        const __m128i magnitudeMask = _mm_set1_epi32(0x7fffffffu);
        const __m128i magnitude = _mm_and_si128(_mm_castps_si128(result), magnitudeMask);
        const __m128i normal = _mm_and_si128(_mm_cmpgt_epi32(magnitude, _mm_set1_epi32(0x007fffffu)),
                                            _mm_cmplt_epi32(magnitude, _mm_set1_epi32(0x7f7fffffu)));
        const auto mask = [](__m128i bits) PS2_VU_INLINE_LAMBDA { return _mm_movemask_ps(_mm_castsi128_ps(bits)); };
        constexpr int active = packedLaneMask[destination];
        const int normalLanes = mask(normal) & active;
        int zeroLanes = 0;
        if (normalLanes != active)
        {
            const __m128i zero = _mm_setzero_si128();
            const __m128i leftBits = _mm_castps_si128(left);
            const __m128i rightBits = _mm_castps_si128(right);
            const __m128i bothZero = _mm_cmpeq_epi32(_mm_and_si128(_mm_or_si128(leftBits, rightBits), magnitudeMask), zero);
            const __m128i cancels = _mm_cmpeq_epi32(leftBits,
                add ? _mm_xor_si128(rightBits, _mm_set1_epi32(INT32_MIN)) : rightBits);
            zeroLanes = mask(_mm_and_si128(_mm_cmpeq_epi32(magnitude, zero), _mm_or_si128(cancels, bothZero))) & active;
            // A zero caused by host flush-to-zero still needs exact underflow flags.
            if ((normalLanes | zeroLanes) != active)
                return false;
        }

        const uint32_t zeros = packedLaneMask[zeroLanes];
        const uint32_t signs = packedLaneMask[_mm_movemask_ps(result) & active];
        Sink{ctx}.fmac(zeros | (signs << 4u), (zeros != 0u) | ((signs != 0u) << 1u), 0u);
        if constexpr (accumulator)
            storePackedLanes<destination>(ctx.vu0_acc, result);
        else if constexpr (fd != 0u)
            storePackedLanes<destination>(ctx.vu0_vf[fd], result);
        return true;
    }

    inline const bool packedArithmeticEnabled = [] {
        const char *value = std::getenv("DECOMP_PS2_VU0_PACKED_ARITHMETIC");
        return value && value[0] == '1' && value[1] == '\0';
    }();
#else
    struct Rounding {
        int previous=std::fegetround();
        Rounding() { std::fesetround(FE_TOWARDZERO); }
        ~Rounding() { std::fesetround(previous); }
    };
#endif
}
// Keep each literal's arithmetic in one native function. Inlining the full
// arithmetic engine into every EE call site can exhaust compiler memory when
// several generated functions share a compilation batch.
#if defined(_MSC_VER)
#define DECOMP_VU0_NOINLINE __declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
#define DECOMP_VU0_NOINLINE __attribute__((noinline))
#else
#define DECOMP_VU0_NOINLINE
#endif
template<uint32_t Word> DECOMP_VU0_NOINLINE void vu_upper(R5900Context &ctx) {
    // VF0 is a hardwired vector, independent of a host context's zero-fill.
    ctx.vu0_vf[0]=_mm_set_ps(1.0f,0.0f,0.0f,0.0f);
#if defined(_WIN64) && (defined(_M_X64) || defined(__x86_64__))
    if constexpr (vu0_detail::isMinMax(Word))
        vu0_detail::selectMinMax<Word>(ctx);
    else
#endif
    {
#if defined(_WIN64) && (defined(_M_X64) || defined(__x86_64__))
        if (vu0_detail::packedArithmeticEnabled)
        {
            if constexpr (vu0_detail::packedAddSubWord<Word>())
            {
                if (vu0_detail::tryPackedAddSub<Word>(ctx))
                    return;
            }
        }
#endif
        constexpr unsigned fs = (Word >> 11) & 31, ft = (Word >> 16) & 31;
        float left[4], right[4], accumulator[4];
        std::memcpy(left, &ctx.vu0_vf[fs], 16);
        std::memcpy(right, &ctx.vu0_vf[ft], 16);
        std::memcpy(accumulator, &ctx.vu0_acc, 16);
        if constexpr (fs == 0) { left[0]=left[1]=left[2]=0; left[3]=1; }
        if constexpr (ft == 0) { right[0]=right[1]=right[2]=0; right[3]=1; }
        vu0_detail::Inputs inputs{left,right,accumulator,ctx.vu0_i,ctx.vu0_q};
        vu0_detail::Sink sink{ctx};
        vu0_detail::Rounding rounding;
        // Word is fixed in generated C++; no guest instruction is fetched and no
        // guest-code compiler runs on this path.
#if defined(_WIN64) && (defined(_M_X64) || defined(__x86_64__))
        if (vu0_detail::tryBroadcastMadd<Word>(inputs, sink))
            return;
#endif
        ps2_vu_detail::upper::computeUpper(Word,inputs,sink);
    }
}
#undef DECOMP_VU0_NOINLINE
}
#endif
