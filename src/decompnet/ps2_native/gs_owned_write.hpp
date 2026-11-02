// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include "gfx/gs/gs_vram.h"
#include "runtime/gs/ps2_gs_memory.h"
#include "runtime/gs/ps2_gs_psmct32.h"
#include <algorithm>
#include <cstddef>

namespace decomp_ps2::graphics {
inline void writeOwnedCt32(uint8_t *data, uint32_t base, uint32_t bufferWidth,
        uint32_t x0, uint32_t y0, uint32_t x1, uint32_t y1,
        const dq8::gfx::GsPageSet &owned, const uint8_t *pixels) {
    if (x0 >= x1 || y0 >= y1 || owned.none()) return;
    const uint32_t width = x1 - x0;
    for (uint32_t y = y0; y < y1; ++y) {
        const uint8_t *row = pixels + size_t(y - y0) * width * 4u;
        for (uint32_t x = x0; x < x1;) {
            // CT32's 8x8 blocks occupy 256 bytes. Their individual rows stay
            // in one physical page even when the buffer base is not page-aligned.
            const uint32_t end = std::min(x1, (x & ~7u) + 8u);
            const uint32_t page = (GSPSMCT32::addrPSMCT32(base, bufferWidth, x, y) >> 13u)
                                  % dq8::gfx::kGsPageCount;
            if (owned.test(page))
                GSMem::WriteRunCT32(data, base, bufferWidth, x0, x1, x, y,
                                   row + (x - x0) * 4u, end - x);
            x = end;
        }
    }
}
}
