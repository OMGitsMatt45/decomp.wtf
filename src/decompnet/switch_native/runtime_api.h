#pragma once
#include "cpu.h"
#include "layout.h"

typedef struct SwitchModule {
    const char *name, *file, *sha256;
    uint64_t base, size, text_offset, text_size, data_offset, data_size;
    const uint64_t *addresses;
    const GuestFn *functions;
    const uint64_t *count;
} SwitchModule;
extern const SwitchModule switch_modules[MODULE_COUNT];
extern const uint64_t switch_initializers[], switch_initializer_count;

typedef struct RtHost {
    void (*call)(Cpu *);
    void (*svc)(Cpu *, uint32_t, uint64_t);
    void (*trap)(Cpu *, uint32_t, uint32_t, uint64_t);
    uint64_t (*ticks)(void);
    void *(*resolve_hle)(uint64_t);
    void (*call_hle)(void *, Cpu *);
} RtHost;
void nx_rt_init(const RtHost *);
int nx_rt_add_module(const uint64_t *, const GuestFn *, uint64_t);
void nx_rt_enter(Cpu *);

void switch_fail(const char *, uint64_t) __attribute__((noreturn));
void switch_exit(void) __attribute__((noreturn));
void *switch_memory(uint64_t address, uint64_t size, int writable);
uint64_t switch_ticks(void);
void switch_svc(Cpu *, uint32_t, uint64_t);

extern uint64_t switch_heap_size, switch_svc_counts[128], switch_ipc_calls;
extern uint64_t switch_debug_bytes, switch_last_svc, switch_last_ipc;
