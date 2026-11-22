"""Batch native 4-bit GS transfers and texture expansion on the pinned runtime."""

from pathlib import Path

from .runtime_patch import replace


def patch(root):
    root = Path(root)
    runtime = root / "thirdparty/PS2Recomp/ps2xRuntime"
    memory = runtime / "src/lib/gs/ps2_gs_memory.cpp"
    header = runtime / "include/runtime/gs/ps2_gs_memory.h"
    transfer = root / "src/gfx/gs/gs_transfer.cpp"
    textures = root / "src/gfx/backends/sdlgpu/sdlgpu_textures.cpp"

    replace(memory, '''#include <array>
''', '''#include <algorithm>
#include <array>
''')
    replace(memory, '    void WriteP4(u8*', '''    namespace
    {
        constexpr auto p4PageExtent = P4Traits::PageExtent();
        constexpr u32 p4PageBytes = static_cast<u32>(P4Traits::PixelsPerPage() / 2u);

        constexpr u32 p4ByteAddress(u32 pageByte, u32 nibbleOffset)
        {
            // An unaligned GS base block can move offsets into the next page.
            return (pageByte + nibbleOffset / 2u) & (MEMORY_SIZE - 1u);
        }
    }

    void WriteRunP4(u8* data, u32 bp, u32 bw, u32 dsax, u32 rowEnd, u32 x, u32 y,
                    const u8* src, u32 count)
    {
        u8 packed = 0u;
        bool pendingHigh = false;
        const auto &page = PageTableP4[bp % P4Traits::BlocksPerPage()];
        while (count != 0u)
        {
            const u32 column = x % p4PageExtent.x;
            const u32 rowPixels = x < rowEnd ? rowEnd - x : 1u;
            const u32 span = std::min(count, std::min(rowPixels, p4PageExtent.x - column));
            const u32 pageByte = static_cast<u32>(P4Traits::PageId(bp, bw, x, y)) * p4PageBytes;
            const auto &offsets = page[y % p4PageExtent.y];
            const auto write = [&](u32 index, u8 value) {
                const u32 offset = offsets[column + index];
                u8 &pixel = data[p4ByteAddress(pageByte, offset)];
                const u32 shift = (offset & 1u) * 4u;
                pixel = static_cast<u8>((pixel & ~(0x0fu << shift)) | ((value & 0x0fu) << shift));
            };

            // Keep both nibbles of a source byte together even when pixel
            // destinations cross a row or page. A destination may alias src.
            u32 index = 0u;
            if (pendingHigh)
                write(index++, packed >> 4u);
            for (; index + 1u < span; index += 2u)
            {
                packed = *src++;
                write(index, packed);
                write(index + 1u, packed >> 4u);
            }
            pendingHigh = index < span;
            if (pendingHigh)
            {
                packed = *src++;
                write(index, packed);
            }

            count -= span;
            x += span;
            if (x >= rowEnd)
            {
                x = dsax;
                ++y;
            }
        }
    }

    void WriteP4(u8*''')
    replace(memory, '    u32 ReadP4(u8*', '''    void ReadRowP4(u8* data, u32 bp, u32 bw, u32 x, u32 y, u32 count, u8* out)
    {
        const auto &offsets = PageTableP4[bp % P4Traits::BlocksPerPage()][y % p4PageExtent.y];
        const u32 rowPage = static_cast<u32>(P4Traits::PageId(bp, bw, 0u, y));
        while (count != 0u)
        {
            const u32 column = x % p4PageExtent.x;
            const u32 span = std::min(count, p4PageExtent.x - column);
            const u32 pageByte = (rowPage + x / p4PageExtent.x) * p4PageBytes;
            for (u32 index = 0u; index < span; ++index)
            {
                const u32 offset = offsets[column + index];
                out[index] = (data[p4ByteAddress(pageByte, offset)] >> ((offset & 1u) * 4u)) & 0x0fu;
            }

            count -= span;
            x += span;
            out += span;
        }
    }

    u32 ReadP4(u8*''')
    replace(header, '\tvoid WriteP4(u8*', '''	// Source bytes pack the first pixel in the low nibble.
	void WriteRunP4(u8* data, u32 bp, u32 bw, u32 dsax, u32 rowEnd, u32 x, u32 y,
	                const u8* src, u32 count);
	void WriteP4(u8*''')
    replace(header, '\tu32 ReadP4(u8*', '''	// A row span unpacked to one palette index per byte.
	void ReadRowP4(u8* data, u32 bp, u32 bw, u32 x, u32 y, u32 count, u8* out);
	u32 ReadP4(u8*''')
    replace(transfer, '''
    while (offset < sizeBytes && m_state.direction == kHostToLocal) {''', '''
    if (dpsm == GS_PSM_T4) {
        const uint32_t remaining = m_state.totalPixels - m_state.copiedPixels;
        const uint32_t available = static_cast<uint32_t>(
            std::min<uint64_t>(remaining, static_cast<uint64_t>(sizeBytes) * 2u));
        if (available != 0u) {
            GSMem::WriteRunP4(m_vram.data(), dbp, dbw, dsax, dsax + rrw, m_state.x, m_state.y,
                              data, available);
            offset = (available + 1u) / 2u;
            wrote = true;
            advance(available);
        }
    }

    while (offset < sizeBytes && m_state.direction == kHostToLocal) {''')
    replace(transfer, '''        case GS_PSM_T4:
        case GS_PSM_T4HL:
''', '''        case GS_PSM_T4HL:
''')
    replace(textures, '''        case GS_PSM_T8: {
            uint8_t *raw = m_rawRow.data();''', '''        case GS_PSM_T4: {
            uint8_t *raw = m_rawRow.data();
            if (m_vram.attached()) {
                GSMem::ReadRowP4(m_vram.data(), key.tbp0, key.tbw, region.x0, y, regionWidth, raw);
            } else {
                std::fill_n(raw, regionWidth, 0u);
            }
            // The old hash reads a 64-bit word per texel. Each 4-bit index
            // contributes one byte followed by seven zero bytes.
            constexpr uint64_t prime = 1099511628211ull;
            constexpr uint64_t primeSquared = prime * prime;
            constexpr uint64_t primeFourth = primeSquared * primeSquared;
            constexpr uint64_t primeEighth = primeFourth * primeFourth;
            for (uint32_t x = 0; x < regionWidth; ++x) {
                const uint8_t index = raw[x];
                texelHash = (texelHash ^ index) * primeEighth;
                const uint32_t color = m_clutRgba[index];
                const size_t offset = static_cast<size_t>(x) * 4u;
                row[offset] = static_cast<uint8_t>(color);
                row[offset + 1u] = static_cast<uint8_t>(color >> 8u);
                row[offset + 2u] = static_cast<uint8_t>(color >> 16u);
                row[offset + 3u] = static_cast<uint8_t>(color >> 24u);
            }
            continue;
        }
        case GS_PSM_T8: {
            uint8_t *raw = m_rawRow.data();''')
