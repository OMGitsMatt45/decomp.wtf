// SPDX-License-Identifier: GPL-3.0-only
// Included inside ps2_vu_program after the decoded instruction helpers.
namespace sse_plain {
inline __m128 normalize(__m128 value) {
    const __m128i bits=_mm_castps_si128(value);
    const __m128i sign=_mm_and_si128(bits,_mm_set1_epi32(INT32_MIN));
    const __m128i exponent=_mm_and_si128(bits,_mm_set1_epi32(0x7f800000));
    const __m128i zero=_mm_cmpeq_epi32(exponent,_mm_setzero_si128());
    const __m128i special=_mm_cmpeq_epi32(exponent,_mm_set1_epi32(0x7f800000));
    const __m128i finite=_mm_or_si128(sign,_mm_set1_epi32(0x7f7fffff));
    const __m128i flushed=_mm_or_si128(_mm_and_si128(zero,sign),_mm_andnot_si128(zero,bits));
    return _mm_castsi128_ps(_mm_or_si128(_mm_and_si128(special,finite),_mm_andnot_si128(special,flushed)));
}
template<uint32_t Upper>
PS2_VU_FORCE_INLINE uint32_t run(const VU1State &state,float *value) {
    constexpr uint32_t code=upperCode(Upper);
    constexpr bool special=(Upper&0x3fu)>=0x3cu;
    constexpr uint32_t fs=(Upper>>11u)&31u,ft=(Upper>>16u)&31u;
    const __m128 source=_mm_loadu_ps(state.vf[fs]);
    if constexpr(special&&code>=0x10u&&code<=0x13u) {
        constexpr float inverse=(code&3u)==0u?1.f:(code&3u)==1u?1.f/16.f:(code&3u)==2u?1.f/4096.f:1.f/32768.f;
        _mm_storeu_ps(value,_mm_mul_ps(_mm_cvtepi32_ps(_mm_castps_si128(source)),_mm_set1_ps(inverse)));
    } else if constexpr(special&&code>=0x14u&&code<=0x17u) {
        constexpr float scale=(code&3u)==0u?1.f:(code&3u)==1u?16.f:(code&3u)==2u?4096.f:32768.f;
        // Bound before multiplying, so finite PS2 operands cannot overflow the
        // host float. Convert only representable int32 values: SSE's invalid
        // conversion sentinel otherwise confuses positive and negative limits.
        const __m128 bound=_mm_set1_ps(2147483648.f/scale);
        const __m128 bounded=_mm_max_ps(_mm_sub_ps(_mm_setzero_ps(),bound),_mm_min_ps(normalize(source),bound));
        const __m128 scaled=_mm_mul_ps(bounded,_mm_set1_ps(scale));
        const __m128i high=_mm_castps_si128(_mm_cmpge_ps(scaled,_mm_set1_ps(2147483648.f)));
        const __m128i integer=_mm_cvttps_epi32(_mm_min_ps(scaled,_mm_set1_ps(2147483520.f)));
        const __m128i result=_mm_or_si128(_mm_and_si128(high,_mm_set1_epi32(INT32_MAX)),_mm_andnot_si128(high,integer));
        _mm_storeu_ps(value,_mm_castsi128_ps(result));
    } else if constexpr(special&&code==0x1du) {
        _mm_storeu_ps(value,_mm_and_ps(normalize(source),_mm_castsi128_ps(_mm_set1_epi32(INT32_MAX))));
    } else if constexpr(special&&code==0x1fu) {
        uint32_t w;std::memcpy(&w,&state.vf[ft][3],4);
        const int32_t limit=(w&0x7f800000u)?int32_t(w&0x7fffffffu):0x007fffff;
        const __m128i bits=_mm_castps_si128(source),bound=_mm_set1_epi32(limit);
        const uint32_t above=_mm_movemask_ps(_mm_castsi128_ps(_mm_cmpgt_epi32(bits,bound)));
        const uint32_t below=_mm_movemask_ps(_mm_castsi128_ps(_mm_cmpgt_epi32(_mm_xor_si128(bits,_mm_set1_epi32(INT32_MIN)),bound)));
        return (above&1u)|((below&1u)<<1u)|((above&2u)<<1u)|((below&2u)<<2u)|((above&4u)<<2u)|((below&4u)<<3u);
    } else {
        static_assert(!special,"unexpected instruction without FMAC flags");
        __m128 right;
        if constexpr(code<=0x17u)right=_mm_set1_ps(state.vf[ft][code&3u]);
        else if constexpr(code==0x1du||code==0x1fu)right=_mm_set1_ps(state.i);
        else right=_mm_loadu_ps(state.vf[ft]);
        constexpr bool maximum=code<=0x13u||code==0x1du||code==0x2bu;
        const __m128 left=normalize(source);right=normalize(right);
        _mm_storeu_ps(value,maximum?_mm_max_ps(left,right):_mm_min_ps(left,right));
    }
    return 0u;
}
}
