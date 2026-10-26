// SPDX-License-Identifier: MIT
// Optional owner BIOS execution. No Nintendo code or BIOS image is supplied.
#include "anygba/system.hpp"
#include "anygba/sha256.h"
#include <algorithm>

namespace anygba {
void System::set_bios_image(std::span<const uint8_t> image) {
    if (image.size() != Memory::kBiosSize) throw Error("GBA BIOS must contain exactly 16384 bytes");
    const bool native=options_.compiled_bios && options_.compiled_bios->sha256 &&
        options_.compiled_bios->arm && options_.compiled_bios->thumb &&
        sha256_hex(image)==options_.compiled_bios->sha256;
    if (options_.strict_static && !native) throw Error("strict static mode rejects interpreted BIOS execution; translate the matching BIOS at export time");
    std::copy(image.begin(), image.end(), mem_.bios.begin());
    bios_image_loaded_ = true;
    bios_native_image_ = native;
}

void System::validate_bios_native() {
    bios_native_image_=bios_image_loaded_ && options_.compiled_bios && options_.compiled_bios->sha256 &&
        options_.compiled_bios->arm && options_.compiled_bios->thumb &&
        sha256_hex(mem_.bios)==options_.compiled_bios->sha256;
    if (options_.strict_static && bios_image_loaded_ && !bios_native_image_)
        throw Error("snapshot BIOS does not match the translated native image");
}

void System::bios_native_enter(uint32_t address,bool thumb) {
    ++bios_native_instructions_;
    cpu_.r[15]=address;
    bios_prefetch(address,thumb);
}

void System::bios_prefetch(uint32_t address, bool thumb) {
    if (!bios_image_loaded_ || address >= Memory::kBiosSize) return;
    // ARM7's three-stage pipeline has fetched PC+8 (ARM) or PC+4 (Thumb)
    // before executing this instruction. Protected reads retain that bus value
    // when a branch leaves the BIOS. Fetch directly: data reads must not latch.
    const auto next = (address + (thumb ? 4u : 8u)) & (Memory::kBiosSize - 1);
    last_bios_opcode_ = 0;
    for (unsigned i=0; i<(thumb ? 2u : 4u); ++i)
        last_bios_opcode_ |= uint32_t(mem_.bios[next+i]) << (8*i);
}

void System::bios_irq(uint32_t return_pc) {
    // deliver_irq() has already entered IRQ mode and set SPSR/LR. The image
    // owns the vector, stack frame, cartridge callback and exception return.
    cpu_.r[15] = 0x18;
    if (cpu_.ret_depth >= ANYGBA_RET_STACK) unwind();
    cpu_.ret_stack[cpu_.ret_depth++] = return_pc;
    ++bios_irq_depth_;
    const int unwinding = resume(return_pc);
    --bios_irq_depth_;
    --cpu_.ret_depth;
    if (unwinding || cpu_.r[15] != return_pc) unwind();
}

void System::bios_swi() {
    // ARM7TDMI SWI exception entry. The supplied vector and epilogue own the
    // register saves and restore CPSR/Thumb state using the supervisor bank.
    const auto saved = ag_cpsr(&cpu_);
    const auto return_pc = cpu_.r[15];
    set_cpsr((saved & ~0x3fu) | 0x80u | ANYGBA_MODE_SVC);
    cpu_.spsr = saved;
    cpu_.r[14] = return_pc;
    cpu_.r[15] = 8;
    if (cpu_.ret_depth >= ANYGBA_RET_STACK) unwind();
    cpu_.ret_stack[cpu_.ret_depth++] = return_pc;
    const int unwinding = resume(return_pc);
    --cpu_.ret_depth;
    if (unwinding) unwind();
}
}

extern "C" void anygba_bios_enter(anygba_cpu* cpu,uint32_t address,int thumb) {
    anygba::system_of(cpu).bios_native_enter(address,thumb!=0);
}
