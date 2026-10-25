// SPDX-License-Identifier: MIT
// Optional owner BIOS execution. No Nintendo code or BIOS image is supplied.
#include "anygba/system.hpp"
#include <algorithm>

namespace anygba {
void System::set_bios_image(std::span<const uint8_t> image) {
    if (image.size() != Memory::kBiosSize) throw Error("GBA BIOS must contain exactly 16384 bytes");
    if (options_.strict_static) throw Error("strict static mode rejects interpreted BIOS execution");
    std::copy(image.begin(), image.end(), mem_.bios.begin());
    bios_image_loaded_ = true;
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
