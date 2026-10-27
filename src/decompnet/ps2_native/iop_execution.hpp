// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstdint>

namespace decomp_ps2::execution {
inline std::atomic<uint64_t> iop_native_instructions{0};
inline std::atomic<uint64_t> iop_interpreted_instructions{0};
inline std::atomic<uint64_t> iop_coverage_misses{0};
inline std::atomic<uint32_t> iop_coverage_pc{0};
inline void iop_gap(uint32_t pc) {
    iop_coverage_pc.store(pc,std::memory_order_relaxed);
    iop_coverage_misses.fetch_add(1,std::memory_order_relaxed);
}
}
