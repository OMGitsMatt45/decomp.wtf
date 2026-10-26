/* SPDX-License-Identifier: MIT. Native firmware identity and dispatch ABI. */
#ifndef DECOMP_GBA_BIOS_NATIVE_H
#define DECOMP_GBA_BIOS_NATIVE_H
#include "anygba/cpu.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct anygba_bios {
    const char* sha256;
    const uint8_t* image;
    const anygba_fn* arm;
    const anygba_fn* thumb;
    uint32_t arm_count,thumb_count;
} anygba_bios;
void anygba_bios_enter(anygba_cpu* cpu,uint32_t address,int thumb);
#ifdef __cplusplus
}
#endif
#endif
