// Original register and DMA conformance checks. RAM payloads are invented.
#include "dsr/machine.h"
#include <cstdint>
#include <iostream>
#include <source_location>
#include <stdexcept>
#include <string>

static void check(bool value, const std::source_location where = std::source_location::current()) {
    if (!value) throw std::runtime_error("DS storage-register conformance failed at line " + std::to_string(where.line()));
}

int main() {
    try {
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
    machine.write16(CpuId::Arm7, 0x04000304, 3);
    check(machine.read32(CpuId::Arm7, 0x04804000) == 0);
    machine.write32(CpuId::Arm7, 0x04804000, 0x12345678);
    // Wireless memory ignores STRB; the same rule applies through the mirror.
    machine.write8(CpuId::Arm7, 0x0480c001, 0xab);
    check(machine.read32(CpuId::Arm7, 0x04804000) == 0x12345678);
    machine.write16(CpuId::Arm7, 0x04805ffe, 0xcdef);
    check(machine.read16(CpuId::Arm7, 0x0480dffe) == 0xcdef);
    machine.write16(CpuId::Arm7, 0x04804158, 0xabcd);
    machine.write16(CpuId::Arm7, 0x04808158, 0x6000);
    check(machine.read16(CpuId::Arm7, 0x0480815c) == 0x6d);
    check(machine.read16(CpuId::Arm7, 0x0480c158) == 0xabcd);
    machine.write16(CpuId::Arm7, 0x04000304, 1);
    check(machine.read32(CpuId::Arm7, 0x04804000) == 0);
    machine.write32(CpuId::Arm7, 0x04804000, 0);
    machine.write16(CpuId::Arm7, 0x04000304, 3);
    check(machine.read32(CpuId::Arm7, 0x04804000) == 0x12345678);
    check(machine.unimplemented_io_count() == 0);
    machine.write32(CpuId::Arm9, 0x04000ff0, 123);
    check(machine.unimplemented_io_count() == 1);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
