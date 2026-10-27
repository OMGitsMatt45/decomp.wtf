// SPDX-License-Identifier: GPL-3.0-only
// The pinned pipeline conductor receives compile-time instruction words only.
#pragma once
#include "ps2_vu1_exec.inl"
#include "ps2_vu1_program.h"

template <uint32_t Instruction>
void ps2_vu_program::Access::decompUpper(VU1Interpreter &vu) {
    vu.execUpperInline(Instruction);
}

template <uint64_t Word>
void ps2_vu_program::Access::decompLower(VU1Interpreter &vu) {
    if constexpr (!(Word & (1ull<<63u)))
        vu.execLowerInline(uint32_t(Word),vu.m_activeVuData,vu.m_activeVuDataSize,
                           *vu.m_activeGs,vu.m_activeMemory,uint32_t(Word>>32u));
}

template <VU1Interpreter::Unit unit,uint64_t Word>
bool ps2_vu_program::Access::decompNativePair(VU1Interpreter &vu,uint64_t budgetEnd,uint32_t codeSize) {
    static constexpr auto decoded=VU1Interpreter::decodeInstructionWords(uint32_t(Word),uint32_t(Word>>32u),unit);
    return decompRunPair(vu,decoded,decompUpper<uint32_t(Word>>32u)>,decompLower<Word>,budgetEnd,codeSize);
}
