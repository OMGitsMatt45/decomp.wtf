// SPDX-License-Identifier: GPL-3.0-only
#include "runtime/gs/gs_cpu_backend.h"
#include "runtime/gs/decomp_vif_gif_worker.hpp"
#include "runtime/gs/gs_frontend.h"
#include "runtime/gs/gs_threaded_backend.h"
#include "runtime/gs/ps2_gif_arbiter.h"
#include "runtime/ps2_memory.h"

#include <algorithm>
#include <cstdio>
#include <initializer_list>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
namespace mailbox = decomp_ps2::vif_gif;
using Bytes = std::vector<uint8_t>;

constexpr uint32_t VifInt = 1u << 11;
constexpr uint32_t Vif1Interrupt = 2u;
constexpr uint32_t Vif1Fbrst = 0x10003c10u;
constexpr uint32_t FirstPixel = 0x11223344u;
constexpr uint32_t LastPixel = 0x55667788u;
constexpr uint64_t FullIdMask = 0xffffffff00000000ull;

void require(bool condition, const char *message)
{
    if (!condition)
        throw std::runtime_error(message);
}

template<class T>
void append(Bytes &bytes, T word)
{
    const auto *begin = reinterpret_cast<const uint8_t *>(&word);
    bytes.insert(bytes.end(), begin, begin + sizeof(word));
}

Bytes registers(std::initializer_list<std::pair<uint64_t, uint64_t>> writes, bool end = true)
{
    Bytes packet;
    append<uint64_t>(packet, (1ull << 60) | (end ? 0x8000ull : 0) | writes.size());
    append<uint64_t>(packet, 0xe); // PACKED A+D
    for (const auto &[address, value] : writes)
    {
        append<uint64_t>(packet, value);
        append<uint64_t>(packet, address);
    }
    return packet;
}

Bytes label(uint32_t value)
{
    return registers({{GS_REG_LABEL, FullIdMask | value}});
}

Bytes pixelUpload(uint32_t pixel)
{
    auto packet = registers({{GS_REG_BITBLTBUF, 1ull << 48}, {GS_REG_TRXPOS, 0},
                             {GS_REG_TRXREG, (1ull << 32) | 1}, {GS_REG_TRXDIR, 0}}, false);
    append<uint64_t>(packet, (2ull << 58) | 0x8001ull); // IMAGE, EOP, one qword
    append<uint64_t>(packet, 0);
    append<uint64_t>(packet, pixel);
    append<uint64_t>(packet, 0);
    return packet;
}

void direct(Bytes &chain, const Bytes &packet)
{
    require(packet.size() % 16 == 0 && packet.size() / 16 <= 0xffff, "invalid DIRECT payload");
    append<uint32_t>(chain, 0x50000000u | static_cast<uint32_t>(packet.size() / 16));
    chain.insert(chain.end(), packet.begin(), packet.end());
}

struct Probe
{
    PS2Memory &memory;
    GS &gs;
    bool async;
    unsigned step = 0;

    uint32_t currentLabel() const { return static_cast<uint32_t>(memory.gs().siglblid >> 32); }

    void clearVifInterrupt()
    {
        require((memory.vif1_regs.stat & VifInt) != 0, "VIF1 STAT.INT missing");
        require(memory.takePendingVifInterrupts() == Vif1Interrupt, "wrong pending VIF1 IRQ");
        require(memory.takePendingVifInterrupts() == 0, "VIF1 IRQ did not drain");
        require(memory.writeIORegister(Vif1Fbrst, 8), "VIF1 FBRST write was rejected");
        require((memory.vif1_regs.stat & VifInt) == 0, "VIF1 FBRST did not clear STAT.INT");
    }

    void mscal(uint32_t pc, uint32_t top, uint32_t itop)
    {
        require((mailbox::activeScope != nullptr) == async, "wrong scope at runtime MSCAL");
        require(top == 10 && itop == 7, "wrong MSCAL TOP/ITOP");
        if (step == 0)
        {
            require(pc == 0x180 && currentLabel() == 0x1111, "IRQ MSCAL missed preceding LABEL");
            require(static_cast<uint32_t>(memory.gs().siglblid) == 0x1234, "IRQ MSCAL missed SIGNAL ID");
            require((memory.gs().csr.load() & 3) == 3, "IRQ MSCAL missed GS SIGNAL or FINISH");
            clearVifInterrupt();
            const auto packet = label(0x3311);
            memory.submitGifPacket(GifPathId::Path1, packet.data(), static_cast<uint32_t>(packet.size()));
            // This small packet must be staged until the following IRQ.
            require(currentLabel() == (async ? 0x1111u : 0x3311u), "wrong PATH1 admission mode");
        }
        else
        {
            require(step == 2 && pc == 0x188, "unexpected MSCAL order");
            require(currentLabel() == 0x4455, "oversized DIRECT did not run after queued LABEL");
            require(memory.takePendingVifInterrupts() == 0, "ordinary MSCAL set a VIF1 IRQ");
        }
        ++step;
    }

    void mscnt(uint32_t top, uint32_t itop)
    {
        require((mailbox::activeScope != nullptr) == async, "wrong scope at MSCNT");
        require(top == 30 && itop == 7, "wrong MSCNT TOP/ITOP");
        clearVifInterrupt();
        if (step == 1)
        {
            require(currentLabel() == 0x3322, "custom observer missed PATH1 then DIRECT order");
            const auto packet = label(0x3333);
            memory.submitGifPacket(GifPathId::Path1, packet.data(), static_cast<uint32_t>(packet.size()));
            require(currentLabel() == (async ? 0x3322u : 0x3333u), "wrong MSCNT PATH1 admission mode");
        }
        else
        {
            require(step == 3 && currentLabel() == 0x4455, "unexpected custom observer order");
            require(gs.ReadVram(GS_PSM_CT32, 0, 1, 0, 0) == FirstPixel, "custom observer missed image upload");
        }
        ++step;
    }
};

struct Result
{
    uint64_t siglblid, csr, vramHash;
    bool operator==(const Result &) const = default;
};

Result run(bool enabled, bool customCallback, bool customSink)
{
    PS2Memory memory;
    require(memory.initialize(), "PS2 memory initialization failed");
    GS gs;
    gs.init(memory.getGSVRAM(), static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &memory.gs());
    gs.setRasterBackend(std::make_unique<GSThreadedBackend>(std::make_unique<GSCpuBackend>()));
    if (enabled)
        gs.enableVifGifWorker();
    GifArbiter arbiter;
    if (customSink)
        arbiter.setProcessPacketFn([&](const uint8_t *data, uint32_t size) { gs.processGIFPacket(data, size); });
    else
        arbiter.bindRuntimeGs(gs);
    memory.setGifArbiter(&arbiter);
    auto *boundary = arbiter.vifGifWorkerBoundary();
    require((boundary != nullptr) == (enabled && !customSink), "wrong GS sink eligibility");
    mailbox::ThreadSession session(&memory, &arbiter, boundary);
    bool async = false;
#if defined(_M_X64) || defined(__x86_64__)
    async = enabled && !customCallback && !customSink;
#endif
    Probe probe{memory, gs, async};
    memory.setVu1MscalCallback(mailbox::RuntimeMscal{
        &memory, &probe, [](void *context, uint32_t pc, uint32_t top, uint32_t itop) {
            static_cast<Probe *>(context)->mscal(pc, top, itop);
        }});
    if (customCallback)
        memory.setVu1MscntCallback([&](uint32_t top, uint32_t itop) { probe.mscnt(top, itop); });
    else
        memory.setVu1MscntCallback(mailbox::RuntimeMscnt{
            &memory, &probe, [](void *context, uint32_t top, uint32_t itop) {
                static_cast<Probe *>(context)->mscnt(top, itop);
            }});

    Bytes chain;
    append<uint32_t>(chain, 0x0300000au); // BASE 10
    append<uint32_t>(chain, 0x02000014u); // OFFSET 20
    append<uint32_t>(chain, 0x04000007u); // ITOP 7
    direct(chain, registers({{GS_REG_LABEL, FullIdMask | 0x1111},
                             {GS_REG_SIGNAL, FullIdMask | 0x1234}, {GS_REG_FINISH, 0}}));
    append<uint32_t>(chain, 0x94000030u); // IRQ MSCAL
    direct(chain, registers({{GS_REG_LABEL, (0xffull << 32) | 0x22}}));
    append<uint32_t>(chain, 0x97000000u); // IRQ MSCNT

    direct(chain, label(0x4444));
    Bytes large(528u * 1024u);
    for (size_t offset = 0; offset < large.size(); offset += 16)
        large[offset + 1] = 0x80; // complete empty GIF tags
    // The masked write depends on the queued LABEL running before this fallback.
    const auto maskedLabel = registers({{GS_REG_LABEL, (0xffull << 32) | 0x55}});
    std::copy(maskedLabel.begin(), maskedLabel.end(), large.end() - maskedLabel.size());
    direct(chain, large);
    append<uint32_t>(chain, 0x14000031u); // ordinary MSCAL with no implicit fence

    direct(chain, pixelUpload(FirstPixel));
    append<uint32_t>(chain, 0x97000000u); // IRQ MSCNT
    direct(chain, pixelUpload(LastPixel));
    append<uint32_t>(chain, 0x11000000u); // FLUSH
    direct(chain, label(0x6666));
    append<uint32_t>(chain, 0x13000000u); // FLUSHA
    append<uint32_t>(chain, 0x80000000u); // IRQ NOP
    direct(chain, label(0x7777));        // only the scope-exit fence publishes this packet

    memory.processVIF1Data(chain.data(), static_cast<uint32_t>(chain.size()));
    require(probe.step == 4 && !mailbox::activeScope, "VIF1 scope did not finish");
    const auto &regs = memory.vif1_regs;
    require(regs.stat == VifInt && regs.top == 30 && regs.tops == 10 && regs.itop == 7 &&
            regs.code == 0x50000002u, "final VIF1 state differs");
    require(probe.currentLabel() == 0x7777, "scope exit did not finish final DIRECT");
    probe.clearVifInterrupt();
    const auto lastPixel = gs.ReadVram(GS_PSM_CT32, 0, 1, 0, 0);
    require(lastPixel == LastPixel, "last image upload differs");

    uint64_t vramHash = 14695981039346656037ull;
    const auto *vram = memory.getGSVRAM();
    for (size_t i = 0; i < PS2_GS_VRAM_SIZE; ++i)
    {
        vramHash ^= vram[i];
        vramHash *= 1099511628211ull;
    }
    return {memory.gs().siglblid, memory.gs().csr.load(), vramHash};
}
}

int main()
try
{
    const auto reference = run(false, false, false);
    require(run(true, false, false) == reference, "worker VIF/GS/VRAM state differs");
    require(run(true, true, false) == reference, "custom callback fallback state differs");
    require(run(true, false, true) == reference, "custom sink fallback state differs");
    std::printf("VIF1 and GS state match across inline, worker, and fallback runs. VRAM hash %016llx\n",
                static_cast<unsigned long long>(reference.vramHash));
    return 0;
}
catch (const std::exception &error)
{
    std::fprintf(stderr, "VIF/GIF worker qualification failed: %s\n", error.what());
    return 1;
}
