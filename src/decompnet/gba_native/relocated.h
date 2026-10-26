/* SPDX-License-Identifier: MIT */
#pragma once
#include <anygba/cpu.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct anygba_relocated_entry {
    uint32_t prefix, source, size, offset, thumb;
    anygba_fn fn;
} anygba_relocated_entry;
extern const anygba_relocated_entry* const anygba_relocated_entries;
extern const uint32_t anygba_relocated_count;
#ifdef __cplusplus
}
#endif
