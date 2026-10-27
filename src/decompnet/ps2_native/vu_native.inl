// SPDX-License-Identifier: GPL-3.0-only
// The pinned pipeline conductor receives compile-time instruction words only.
#pragma once
#include "ps2_vu1_exec.inl"
#include "ps2_vu1_program.h"

template <VU1Interpreter::Unit unit,uint64_t Word>
bool ps2_vu_program::Access::decompNativePair(VU1Interpreter &vu,uint64_t budgetEnd,uint32_t codeSize) {
    static constexpr auto decoded=VU1Interpreter::decodeInstructionWords(uint32_t(Word),uint32_t(Word>>32u),unit);
    return vu.runDecodedPair<true>(decoded,budgetEnd,codeSize);
}
