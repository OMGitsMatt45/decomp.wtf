// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstdint>

namespace decomp_ps2::execution {
inline std::atomic<uint64_t> vu_native_pairs{0},vu_interpreted_pairs{0},vu_coverage_misses{0};
inline std::atomic<uint32_t> vu_coverage_pc{0},vu_coverage_unit{0};
inline void vu_gap(uint32_t unit,uint32_t pc) {
    vu_coverage_unit.store(unit,std::memory_order_relaxed);
    vu_coverage_pc.store(pc,std::memory_order_relaxed);
    vu_coverage_misses.fetch_add(1,std::memory_order_relaxed);
}
}
