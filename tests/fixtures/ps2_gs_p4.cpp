#include "runtime/gs/ps2_gs_memory.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <random>
#include <vector>

static void scalarWrite(u8* memory, u32 bp, u32 bw, u32 dsax, u32 end, u32 x, u32 y,
                        const u8* src, u32 count)
{
    const auto put = [&](u8 value) {
        GSMem::WriteP4(memory, bp, bw, x, y, value);
        if (++x >= end) {
            x = dsax;
            ++y;
        }
    };
    while (count >= 2u) {
        const u8 packed = *src++;
        put(packed & 15u);
        put(packed >> 4u);
        count -= 2u;
    }
    if (count)
        put(*src & 15u);
}

int main()
{
    GSMem::InitLookupTables();
    std::mt19937 rng(546401);
    const auto random = [&](u32 end) { return static_cast<u32>(rng()) % end; };
    std::vector<u8> initial(GSMem::MEMORY_SIZE);
    auto expected = initial;
    auto actual = initial;
    for (auto &byte : initial)
        byte = static_cast<u8>(rng());

    for (u32 trial = 0u; trial < 256u; ++trial) {
        auto base = random(16384);
        auto width = random(64);
        auto start = random(2048);
        auto rowWidth = 1u + random(257);
        auto x = start + random(rowWidth);
        auto y = random(2048);
        auto count = random(1024);
        if (trial % 8u == 0u) {
            base = 16383u; width = 5u; start = 127u; rowWidth = 129u;
            x = 127u; y = 127u; count = 1023u;
        } else if (trial % 8u == 1u) {
            base = 0u; width = 4u; start = 0u; rowWidth = 7u;
            x = 0u; y = 2u; count = 91u;
        } else if (trial % 8u == 2u) {
            base = 0xffffffffu; width = 63u; start = 5u; rowWidth = 9u;
            x = 0xffffffffu; y = 0xffffffffu; count = 19u;
        }

        expected = initial;
        actual = initial;
        std::array<u8, 512> payload;
        for (auto &byte : payload)
            byte = static_cast<u8>(rng());
        const bool alias = trial % 8u == 1u || trial % 8u == 3u;
        const auto aliasOffset = trial % 8u == 1u ? 0u : random(4u * 1024u * 1024u - 512u);
        scalarWrite(expected.data(), base, width, start, start + rowWidth, x, y,
                    alias ? expected.data() + aliasOffset : payload.data(), count);
        GSMem::WriteRunP4(actual.data(), base, width, start, start + rowWidth, x, y,
                         alias ? actual.data() + aliasOffset : payload.data(), count);
        if (expected != actual) {
            std::fprintf(stderr, "Native T4 write differences in trial %u\n", trial);
            return 1;
        }

        std::array<u8, 1024> row;
        row.fill(255u);
        GSMem::ReadRowP4(actual.data(), base, width, x, y, count, row.data());
        for (u32 i = 0u; i < count; ++i)
            if (row[i] != GSMem::ReadP4(actual.data(), base, width, x + i, y)) {
                std::fprintf(stderr, "Native T4 row read difference in trial %u, pixel %u\n", trial, i);
                return 1;
            }
        if (!std::all_of(row.begin() + count, row.end(), [](u8 byte) { return byte == 255u; }))
            return 1;
    }

    std::puts("256 bit-exact native T4 read/write trials passed");
}
