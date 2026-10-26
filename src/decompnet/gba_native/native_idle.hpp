// SPDX-License-Identifier: CC0-1.0
// Native counterpart of the original test cartridge's single B-to-self word.
#pragma once
#include <anygba/cpu.h>

static void original_idle_cpu(anygba_cpu* c) {
    AG_ENTER(c,0x08000000u);
    for(;;) {
        AG_SPEND(c,8,1,0);
        AG_TICK(c,0x08000000u);
        c->r[15]=0x08000000u;
        anygba_idle_loop(c);
    }
}
static anygba_game original_idle_game(uint32_t size) {
    static const anygba_function_entry entries[]={
        {0x08000000u,0,original_idle_cpu,0x08000000u,0x08000004u,0}
    };
    return {"Original hardware test","",size,entries,1,"",-1,""};
}
