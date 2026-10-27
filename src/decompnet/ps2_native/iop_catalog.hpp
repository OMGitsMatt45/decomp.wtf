// SPDX-License-Identifier: GPL-3.0-only
// Interface for ahead-of-time translations linked with PS2Recomp's IOP core.
#pragma once
#include "cpu.h"
#include "bus.h"
#include "irx.h"
#include <cstddef>

namespace ps2x::iop::lle {
struct DecompNativeInstruction {
    uint32_t word,mask;
    Cpu::NativeFunction function;
};
struct DecompNativeModule {
    const unsigned char *image;
    uint32_t size,text,entry,gp,bss;
    const IrxImage::Relocation *relocations;
    size_t relocationCount;
    const DecompNativeInstruction *instructions;
};
const DecompNativeModule *decomp_iop_catalog(size_t &count);
}
