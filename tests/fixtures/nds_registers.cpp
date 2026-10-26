// Original register and DMA conformance checks. RAM payloads are invented.
#include "dsr/machine.h"
#include <cstdint>
#include <stdexcept>

static void check(bool value) {
    if (!value) throw std::runtime_error("DS storage-register conformance failed");
}

int main() {
    dsr::MachineConfig config;
    dsr::Machine machine(config);
    using dsr::CpuId;
    for (std::uint32_t channel = 0; channel < 4; ++channel) {
        const auto fill = 0x040000e0u + 4 * channel;
        machine.write32(CpuId::Arm9, fill, 0x12345678u + channel);
        machine.write16(CpuId::Arm9, fill + 2, 0xabcd);
        machine.write8(CpuId::Arm9, fill + 1, 0xef);
        const auto expected = 0xabcdef78u + channel;
        check(machine.read32(CpuId::Arm9, fill) == expected);
        check(machine.read16(CpuId::Arm9, fill + 2) == 0xabcd);
        check(machine.read8(CpuId::Arm9, fill + 1) == 0xef);

        // An immediate, fixed-source, word DMA must read the same latch.
        const auto dma = 0x040000b0u + 12 * channel;
        const auto destination = 0x02001000u + 0x20 * channel;
        machine.write32(CpuId::Arm9, dma, fill);
        machine.write32(CpuId::Arm9, dma + 4, destination);
        machine.write32(CpuId::Arm9, dma + 8, 0x85000003u);
        for (unsigned word = 0; word < 3; ++word)
            check(machine.read32(CpuId::Arm9, destination + 4 * word) == expected);
    }
    const auto keys = machine.read16(CpuId::Arm7, 0x04000136);
    machine.write16(CpuId::Arm7, 0x04000134, 0x8123);
    machine.write8(CpuId::Arm7, 0x04000134, 0x45);
    check(machine.read16(CpuId::Arm7, 0x04000134) == 0x8145);
    machine.write8(CpuId::Arm7, 0x04000135, 0x92);
    check(machine.read16(CpuId::Arm7, 0x04000134) == 0x9245);
    machine.write32(CpuId::Arm7, 0x04000134, 0xffffabcd);
    check(machine.read16(CpuId::Arm7, 0x04000134) == 0xabcd);
    check(machine.read16(CpuId::Arm7, 0x04000136) == keys);
    check(machine.unimplemented_io_count() == 0);
    machine.write32(CpuId::Arm9, 0x04000ff0, 123);
    check(machine.unimplemented_io_count() == 1);
}
