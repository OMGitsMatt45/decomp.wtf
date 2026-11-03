"""Elide FMAC input flushing only after a proven normalizing write."""
from pathlib import Path

from ..pc import PCError


def transform(text):
    def swap(old, new, count=1):
        nonlocal text
        if text.count(old) != count:
            raise PCError('The pinned VU input site changed: '+old[:65])
        text = text.replace(old, new)

    anchor = '// Queued FMAC conditions stay in the MAC register\'s layout, one bit per lane'
    swap(anchor, '''// Infer a normalized input from the most recent writer in this basic block.
// Entry values and raw transfers (including FTOI and lower VF writes) are
// unknown. Limiting the lookback only leaves more of the ordinary checks.
template <const auto &Code, uint32_t Index>
constexpr uint32_t knownNormalized()
{
    constexpr uint32_t word = static_cast<uint32_t>(Code.words[Index] >> 32u);
    if constexpr (!upperPublishesFlags(word) || upperIsNop(word))
        return 0u;
    // A PATH1 observer can run after a kick. Do not rely on values across
    // one, and check for a kick already in progress at block entry.
    for (uint32_t earlier = 0u; earlier < Index; ++earlier)
    {
        const uint64_t pair = Code.words[earlier];
        const uint32_t high = static_cast<uint32_t>(pair >> 32u);
        if ((high & 0x80000000u) == 0u &&
            Access::decode(static_cast<uint32_t>(pair), high).lowerUsage.pipeline == Access::kXgkick)
            return 0u;
    }
    constexpr uint32_t code = upperCode(word);
    constexpr bool fromI = code == 0x1Eu || code == 0x22u || code == 0x23u || code == 0x26u || code == 0x27u;
    constexpr bool broadcast = code <= 0xFu || (code >= 0x18u && code <= 0x1Bu);
    constexpr uint8_t fs = (word >> 11u) & 31u, ft = (word >> 16u) & 31u;
    const auto normalized = [&](uint8_t reg, uint8_t lanes) {
        if (reg == 0u)
            return false;
        for (uint32_t back = 1u; back <= std::min(Index, 32u); ++back)
        {
            const uint64_t pair = Code.words[Index-back];
            const uint32_t upper = static_cast<uint32_t>(pair >> 32u);
            const auto d = Access::decode(static_cast<uint32_t>(pair), upper);
            const auto u = d.upperUsage.vfWrite, l = d.lowerUsage.vfWrite;
            if (l.reg == reg && u.reg != reg && (l.lanes & lanes) != 0u)
                return false;
            if (u.reg == reg && (u.lanes & lanes) != 0u)
            {
                // FMAC results (including the exact fallback) and ordinary
                // float-valued non-FMAC instructions normalize their outputs.
                // FTOI stores raw integer bits in the VF register instead.
                const uint32_t op = upperCode(upper);
                if ((upper & 0x3Fu) >= 0x3Cu && op >= 0x14u && op <= 0x17u)
                    return false;
                lanes &= static_cast<uint8_t>(~u.lanes);
                if (lanes == 0u)
                    return true;
            }
        }
        return false;
    };
    uint32_t mask = normalized(fs, 15u) ? 1u : 0u;
    if constexpr (fromI)
    {
        for (uint32_t back = 1u; back <= std::min(Index, 32u); ++back)
            if ((Code.words[Index-back] & 0x8000000000000000ull) != 0u)
                return mask | 2u;
    }
    else if constexpr (!upperReadsQ(word))
    {
        if (normalized(ft, broadcast ? lane(code & 3u) : 15u))
            mask |= 2u;
    }
    return mask;
}

'''+anchor)
    swap('settledReads<Code, Index>()>(nextPc);', 'settledReads<Code, Index>(), knownNormalized<Code, Index>()>(nextPc);')
    swap('        m_pairs += Pairs;', '        m_blockStartsWithoutKick = !m_kickActive;\n        m_pairs += Pairs;')
    swap('    bool m_taken = false;\n    bool m_kickActive;',
         '    bool m_taken = false;\n    bool m_kickActive;\n    bool m_blockStartsWithoutKick = false;')
    swap('template <uint32_t Pc, uint32_t Lower, uint32_t Upper, uint32_t Settled>',
         'template <uint32_t Pc, uint32_t Lower, uint32_t Upper, uint32_t Settled, uint32_t KnownNormalized>', 2)
    for name in ('upper', 'fastUpper'):
        for prefix in ('', 'Frame::'):
            result = 'void' if name == 'upper' else 'bool'
            swap(f'template <uint32_t Upper>\n'+('    ' if not prefix else '')+f'PS2_VU_FORCE_INLINE {result} {prefix}{name}(float *value)',
                 f'template <uint32_t Upper, uint32_t KnownNormalized>\n'+('    ' if not prefix else '')+f'PS2_VU_FORCE_INLINE {result} {prefix}{name}(float *value)')
    swap('upper<Upper>(upperValue);', 'upper<Upper, KnownNormalized>(upperValue);')
    swap('fastUpper<Upper>(value)', 'fastUpper<Upper, KnownNormalized>(value)')
    for vector, load in (('float32x4_t', 'vld1q_f32'), ('__m128', '_mm_loadu_ps')):
        swap(f'        {vector} left = flushDenormals({load}(m_state.vf[fs]));',
             f'        {vector} left = {load}(m_state.vf[fs]);\n'
             '        if ((KnownNormalized & 1u) == 0u || !m_blockStartsWithoutKick) left = flushDenormals(left);')
    swap('        right = flushDenormals(right);',
         '        if ((KnownNormalized & 2u) == 0u || !m_blockStartsWithoutKick) right = flushDenormals(right);', 2)
    return text


def patch(root):
    header = Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/vu/ps2_vu1_program.h'
    header.write_text(transform(header.read_text(encoding='utf-8')), encoding='utf-8')
