// SPDX-License-Identifier: GPL-3.0-only
#include "gfx/gs/gs_transfer.h"
#include "decomp_owned_write.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using Bytes = std::vector<u8>;

void check(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

void put(bool depth, u8* memory, u32 bp, u32 bw, u32 x, u32 y, const u8* pixel)
{
    u32 value;
    std::memcpy(&value, pixel, sizeof(value));
    (depth ? GSMem::WriteZ32 : GSMem::WriteCT32)(memory, bp, bw, x, y, value);
}

void directCases(const Bytes& initial, const Bytes& payload)
{
    Bytes actual, expected;
    const auto run = [&](bool depth, u32 bp, u32 bw, u32 start, u32 end, u32 x, u32 y,
                         u32 count, bool alias) {
        actual = expected = initial;
        const u8* input = alias ? actual.data() : payload.data() + 1;
        const u8* reference = alias ? expected.data() : payload.data() + 1;
        (depth ? GSMem::WriteRunZ32 : GSMem::WriteRunCT32)(
            actual.data(), bp, bw, start, end, x, y, input, count);
        for (u32 i = 0; i < count; ++i) {
            put(depth, expected.data(), bp, bw, x, y, reference + 4u * i);
            if (++x >= end) {
                x = start;
                ++y;
            }
        }
        check(actual == expected, "32-bit run differs at BP " + std::to_string(bp));
    };

    for (bool depth : {false, true}) {
        for (u32 block = 0; block < 32; ++block) {
            for (u32 page : {0u, 511u}) {
                const u32 bp = page * 32u + block;
                run(depth, bp, 9, 61, 137, 61, 31, 251, false);
                run(depth, bp, 0, 62, 65, 64, 30, 47, false);
                run(depth, bp, 1, 0, 129, 62, 63, 228, false);
            }
        }
        run(depth, 0, 4, 2, 71, 2, 0, 101, true);
        run(depth, 0xffffffffu, 4, 2, 71, 0xffffffffu, 0xffffffffu, 19, false);
        run(depth, 21, 1, 4, 4, 4, 7, 33, false);
        run(depth, 0, 1, 0, 1, 0, 0, 0, false);
    }
    std::puts("392 direct CT32/Z32 runs match full 4 MiB scalar VRAM");
}

void ownershipCases(const Bytes& initial, const Bytes& payload)
{
    Bytes actual, expected;
    constexpr u32 x0 = 61, x1 = 133, y0 = 29, y1 = 35, bw = 3;
    for (u32 bp : {0u, 31u, 32u, 16351u, 16383u}) {
        for (unsigned ownership : {0u, 1u, 2u, 3u}) {
            actual = expected = initial;
            dq8::gfx::GsPageSet owned;
            for (size_t page = 0; page < owned.size(); ++page) {
                if ((page % 2u == 0u && (ownership & 1u)) ||
                    (page % 2u != 0u && (ownership & 2u)))
                    owned.set(page);
            }
            decomp_ps2::graphics::writeOwnedCt32(
                actual.data(), bp, bw, x0, y0, x1, y1, owned, payload.data());
            size_t offset = 0;
            for (u32 y = y0; y < y1; ++y) {
                for (u32 x = x0; x < x1; ++x, offset += 4u) {
                    const u32 address = GSPSMCT32::addrPSMCT32(bp, bw, x, y);
                    const u32 page = (address >> 13u) % dq8::gfx::kGsPageCount;
                    if (owned.test(page))
                        put(false, expected.data(), bp, bw, x, y, payload.data() + offset);
                }
            }
            check(actual == expected, "Unowned or wrapped page differs");
        }
    }
    std::puts("20 owned-page writes preserve unowned VRAM");
}

class TransferCases {
public:
    explicit TransferCases(const Bytes& initial)
        : m_actual(initial), m_expected(initial), m_engine(m_vram)
    {
        m_vram.attach(m_actual.data(), static_cast<u32>(m_actual.size()));
        m_engine.setResolveHook([](const auto&) {
            throw std::runtime_error("Unexpected resolve during a host upload");
        });
        m_engine.setInvalidateHook([&](const auto& pages) {
            check(pages == m_pages, "Host upload invalidated different pages");
            ++m_invalidations;
        });
    }

    void begin(const GSTransferCommand& command)
    {
        if (m_active)
            check(m_actual == m_expected, "Crafted transfer full VRAM differs");
        m_active = command.direction == 0 &&
            (command.bitbltbuf.dpsm == GS_PSM_CT32 || command.bitbltbuf.dpsm == GS_PSM_Z32);
        if (!m_active)
            return;
        m_command = command;
        m_engine.begin(command);
        m_count = 0;
        m_partial = 0;
        const auto& blt = command.bitbltbuf;
        const auto& pos = command.trxpos;
        const auto& reg = command.trxreg;
        m_total = u32(reg.rrw) * reg.rrh;
        m_pages.reset();
        dq8::gfx::gsMarkPages(m_pages, blt.dbp, std::max<u32>(1, blt.dbw),
            blt.dpsm, reg.rrw, reg.rrh, pos.dsax, pos.dsay);
    }

    void upload(const u8* input, u32 size)
    {
        if (!m_active)
            return;
        const auto& blt = m_command.bitbltbuf;
        const auto& pos = m_command.trxpos;
        const u32 width = m_command.trxreg.rrw;
        const u32 before = m_count;
        const u32 invalidations = m_invalidations;
        m_engine.upload(input, size);
        for (u32 i = 0; i < size && m_count < m_total; ++i) {
            m_pixel[m_partial++] = input[i];
            if (m_partial == m_pixel.size()) {
                put(blt.dpsm == GS_PSM_Z32, m_expected.data(), blt.dbp,
                    std::max<u32>(1, blt.dbw), pos.dsax + m_count % width,
                    pos.dsay + m_count / width, m_pixel.data());
                ++m_count;
                m_partial = 0;
            }
        }
        const auto state = m_engine.snapshot();
        check(state.copiedPixels == m_count, "Copied pixel count differs");
        const bool done = m_total != 0 && m_count == m_total;
        check(state.direction == (done ? 3u : 0u), "Transfer direction differs");
        check(state.totalPixels == (done ? 0u : m_total), "Pixel extent differs");
        if (m_total && !done) {
            check(state.x == pos.dsax + m_count % width && state.y == pos.dsay + m_count / width,
                  "Partial transfer cursor differs");
        }
        check(m_invalidations == invalidations + (m_count != before), "Invalidation count differs");
    }

private:
    Bytes m_actual, m_expected;
    dq8::gfx::GsVram m_vram;
    dq8::gfx::GsTransferEngine m_engine;
    GSTransferCommand m_command{};
    dq8::gfx::GsPageSet m_pages;
    std::array<u8, 4> m_pixel{};
    u32 m_count = 0, m_total = 0, m_partial = 0, m_invalidations = 0;
    bool m_active = false;
};

void craftedTransfers(const Bytes& initial, const Bytes& payload)
{
    TransferCases attached(initial);
    dq8::gfx::GsVram unmapped;
    dq8::gfx::GsTransferEngine unmappedEngine(unmapped);
    for (u8 psm : {GS_PSM_CT32, GS_PSM_Z32}) {
        GSTransferCommand command;
        command.direction = 0;
        command.bitbltbuf.dbp = 16383;
        command.bitbltbuf.dbw = 0;
        command.bitbltbuf.dpsm = psm;
        command.trxpos.dsax = 61;
        command.trxpos.dsay = 31;
        command.trxreg.rrw = 73;
        command.trxreg.rrh = 3;
        unmappedEngine.begin(command);
        unmappedEngine.upload(payload.data(), 73u * 3u * 4u);
        check(unmappedEngine.snapshot().copiedPixels == 0u, "Unmapped VRAM accepted data");

        attached.begin(command);
        u32 offset = 0;
        for (u32 size : {0u, 1u, 2u, 1u, 249u, 63u, 5u, 65u, 503u, 52u}) {
            attached.upload(payload.data() + offset, size);
            offset += size;
        }
        attached.begin(command);
        attached.upload(payload.data(), 3u);
        attached.begin(command);
        attached.upload(payload.data() + 19, 32u);
    }
    attached.begin({});
    std::puts("Partial pixels, padding, restart, wrap and unmapped transfer cases match");
}

} // namespace

int main()
{
    try {
        GSMem::InitLookupTables();
        Bytes initial(GSMem::MEMORY_SIZE), payload(8192);
        std::mt19937 random(547023);
        for (auto* buffer : {&initial, &payload}) {
            for (auto& byte : *buffer)
                byte = static_cast<u8>(random());
        }
        directCases(initial, payload);
        ownershipCases(initial, payload);
        craftedTransfers(initial, payload);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
