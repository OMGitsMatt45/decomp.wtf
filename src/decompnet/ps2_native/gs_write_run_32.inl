// SPDX-License-Identifier: GPL-3.0-only
        static_assert([] {
            for (const auto& row : ColumnTable32) {
                for (u32 x = 0; x < row.size(); x += 2u) {
                    if ((row[x] & 1u) != 0u || row[x + 1u] != row[x] + 1u)
                        return false;
                }
            }
            return true;
        }());

        template <PixelStorageMode psm, typename TableT>
        inline void WriteRun32(const TableT& table, u8* data, u32 bp, u32 bw, u32 dsax,
                              u32 rowEnd, u32 x, u32 y, const u8* src, u32 count)
        {
            if (count == 0u)
                return;

            // VRAM can supply pixels to direct callers. Keep their forward,
            // pixel-at-a-time reads when an earlier write can change a later read.
            const auto sourceAddress = reinterpret_cast<std::uintptr_t>(src);
            const auto vramAddress = reinterpret_cast<std::uintptr_t>(data);
            const bool overlapsVram = sourceAddress >= vramAddress
                ? sourceAddress - vramAddress < MEMORY_SIZE
                : vramAddress - sourceAddress < std::uint64_t(count) * sizeof(u32);
            if (overlapsVram || x >= rowEnd || dsax >= rowEnd) {
                WriteRun32Scalar<psm>(table, data, bp, bw, dsax, rowEnd, x, y, src, count);
                return;
            }

            using Traits = PixelStorageTraits<psm>;
            constexpr u32 pageWidth = Traits::PageExtent().x;
            constexpr u32 pageHeight = Traits::PageExtent().y;
            static_assert((Traits::PixelsPerBlock() & 1u) == 0u);
            static_assert((pageWidth & 1u) == 0u);
            const auto& blockTable = table[bp % Traits::BlocksPerPage()];

            while (count != 0u) {
                u32 column = x % pageWidth;
                const u32 span = std::min({count, rowEnd - x, pageWidth - column});
                const auto& offsets = blockTable[y % pageHeight];
                const auto page = Traits::PageId(bp, bw, x, y);
                const auto pageBytes = page * GS_PAGE_SIZE;
                const auto address = [&](u32 offset) {
                    return data + ((pageBytes + offsets[offset] * sizeof(u32)) &
                                   (MEMORY_SIZE - sizeof(u32)));
                };

                const u32 end = column + span;
                if ((column & 1u) != 0u) {
                    std::memcpy(address(column), src, sizeof(u32));
                    ++column;
                    src += sizeof(u32);
                }
                // Each even-x pair shares a swizzled block and starts on an
                // even pixel address, including the last pair before VRAM wraps.
                for (; column + 1u < end; column += 2u) {
                    std::memcpy(address(column), src, 2u * sizeof(u32));
                    src += 2u * sizeof(u32);
                }
                if (column < end) {
                    std::memcpy(address(column), src, sizeof(u32));
                    src += sizeof(u32);
                }

                count -= span;
                x += span;
                if (x == rowEnd) {
                    x = dsax;
                    ++y;
                }
            }
        }
