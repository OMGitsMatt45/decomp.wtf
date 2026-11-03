// SPDX-License-Identifier: CC0-1.0
#include "runtime/ps2_memory.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>

static bool trackLarge = false;
static unsigned largeAllocations = 0;

void *operator new(std::size_t size)
{
    if (trackLarge && size >= 2u*1024u*1024u)
        ++largeAllocations;
    if (void *p = std::malloc(size ? size : 1))
        return p;
    throw std::bad_alloc();
}

void operator delete(void *p) noexcept { std::free(p); }
void operator delete(void *p, std::size_t) noexcept { std::free(p); }

// D1 chain: the two tag-transfer VIF codes precede the payload. The unpack
// crosses the end of VU1 RAM, then MSCAL checks that the command cursor,
// IRQ, and double buffer state all advanced in the original order.
static bool vif1(PS2Memory &mem, unsigned index)
{
    constexpr uint32_t channel = 0x10009000, tagAddress = 0x2000;
    const uint32_t marker = index | 0x8020f001u;
    const std::array<uint32_t, 12> tags{
        0x10000002, 0, 0x01000101, 0xec023fff,
        marker, marker+1, marker+2, marker+3,
        marker+4, marker+5, marker+6, marker+7,
    };
    // Two V4-32 vectors are the full payload; put the next command in a
    // zero-QWC END tag so its TTE words execute immediately afterward.
    const std::array<uint32_t, 4> end{0x70000000, 0, 0x04000037, 0x14000008};
    std::memcpy(mem.getRDRAM()+tagAddress, tags.data(), sizeof(tags));
    std::memcpy(mem.getRDRAM()+tagAddress+sizeof(tags), end.data(), sizeof(end));
    bool called = false, correct = false;
    mem.setVu1MscalCallback([&](uint32_t pc, uint32_t top, uint32_t itop) {
        called = true;
        correct = pc == 64 && top == 0 && itop == 0x37 &&
            std::memcmp(mem.getVU1Data()+16368, tags.data()+4, 16) == 0 &&
            std::memcmp(mem.getVU1Data(), tags.data()+8, 16) == 0;
    });
    mem.writeIORegister(0x1000e010, 2);
    mem.writeIORegister(channel+0x30, tagAddress);
    mem.writeIORegister(channel, 0x144);
    mem.setVu1MscalCallback({});
    const auto irq = mem.takePendingVifInterrupts();
    const auto status = mem.readIORegister(0x1000e010);
    const auto control = mem.readIORegister(channel);
    if (called && correct && irq == 2 && (control & 0x100u) == 0 && (status & 2u) != 0)
        return true;
    std::fprintf(stderr, "D1 callback=%d payload=%d irq=%x control=%x status=%x code=%x\n",
        called, correct, irq, control, status, mem.vif1_regs.code);
    return false;
}

// D2 chain is queued before a sink exists. Mutating source RAM after submission
// must not mutate either submitted tag payload.
static bool gif(PS2Memory &mem, uint32_t index)
{
    constexpr uint32_t channel = 0x1000a000, tagAddress = 0x3000;
    const std::array<uint32_t, 16> tags{
        0x10000001, 0, 0, 0, index, 2, 3, 4,
        0x70000001, 0, 0, 0, index^0x55555555u, 6, 7, 8,
    };
    std::memcpy(mem.getRDRAM()+tagAddress, tags.data(), sizeof(tags));
    mem.writeIORegister(0x1000e010, 4);
    mem.writeIORegister(channel+0x30, tagAddress);
    mem.writeIORegister(channel, 0x104);
    if ((mem.readIORegister(0x1000e010) & 4u) != 0)
    {
        std::fputs("D2 completed before installing a packet sink\n", stderr);
        return false;
    }
    std::memset(mem.getRDRAM()+tagAddress, 0xff, sizeof(tags));
    bool correct = false;
    mem.setGifPacketCallback([&](const uint8_t *bytes, uint32_t size) {
        correct = size == 32 && std::memcmp(bytes, tags.data()+4, 16) == 0 &&
            std::memcmp(bytes+16, tags.data()+12, 16) == 0;
    });
    mem.processPendingTransfers();
    mem.setGifPacketCallback({});
    const auto status = mem.readIORegister(0x1000e010);
    const auto control = mem.readIORegister(channel);
    if (correct && (control & 0x100u) == 0 && (status & 4u) != 0)
        return true;
    std::fprintf(stderr, "D2 payload=%d control=%x status=%x\n", correct, control, status);
    return false;
}

static bool large_vif1(PS2Memory &mem, uint32_t pattern)
{
    constexpr uint32_t channel = 0x10009000, tags = 0x4000, payload = 0x8000;
    constexpr uint32_t blocks = 192, qwords = 1024;
    const std::array<uint32_t, 4> ref{0x30000000u|qwords, payload, 0, 0};
    const std::array<uint32_t, 4> end{0x70000000, 0, 0, 0};
    for (uint32_t i=0; i<blocks; ++i)
        std::memcpy(mem.getRDRAM()+tags+i*16, ref.data(), sizeof(ref));
    std::memcpy(mem.getRDRAM()+tags+blocks*16, end.data(), sizeof(end));
    std::memset(mem.getRDRAM()+payload, 0, qwords*16);
    const std::array<uint32_t, 6> data{0x01000101, 0x6c010001, pattern, 2, 3, 4};
    std::memcpy(mem.getRDRAM()+payload, data.data(), sizeof(data));
    mem.writeIORegister(0x1000e010, 2);
    mem.writeIORegister(channel+0x30, tags);
    mem.writeIORegister(channel, 0x104);
    return std::memcmp(mem.getVU1Data()+16, data.data()+2, 16)==0 &&
        (mem.readIORegister(0x1000e010)&2u)!=0;
}

int main(int argc, char **argv)
{
    PS2Memory mem;
    if (!mem.initialize())
        return 1;
    mem.writeIORegister(0x1000e000, 1);
    if (argc==2 && std::strcmp(argv[1],"--large-chain")==0)
    {
        if (!large_vif1(mem,0x1234))
            return 3;
        trackLarge=true;
        for (uint32_t i=0; i<8; ++i)
            if (!large_vif1(mem,0x77a50000u+i))
                return 4;
        trackLarge=false;
        std::printf("{\"chains\":8,\"bytes_per_chain\":3145728,\"large_allocations_after_warmup\":%u}\n",
                    largeAllocations);
        return 0;
    }
    for (unsigned index = 0; index < 2048; ++index)
        if (!vif1(mem, index) || !gif(mem, index))
        {
            std::fprintf(stderr, "graphics DMA fixture failed at case %u\n", index);
            return 2;
        }
    std::puts("{\"vif1_chains\":2048,\"gif_chains\":2048,\"payload_order_and_irqs_preserved\":true}");
}
