// Native calls unwind only within C. Rust callbacks return before any longjmp.
#include "native_api.h"
#include <setjmp.h>
#include <fenv.h>

typedef struct RtHost {
    void (*call)(Cpu *);
    void (*svc)(Cpu *, uint32_t, uint64_t);
    void (*trap)(Cpu *, uint32_t, uint32_t, uint64_t);
    uint64_t (*ticks)(void);
    void *(*resolve_hle)(uint64_t);
    void (*call_hle)(void *, Cpu *);
} RtHost;
extern void nx_rt_init(const RtHost *);
extern int nx_rt_add_module(const uint64_t *, const GuestFn *, uint64_t);

__thread uintptr_t sw_guest_memory_base;
static __thread jmp_buf *escape;
static __thread Cpu *active;
static __thread uint64_t unhooked;
static __thread unsigned poll_budget;
static __thread const fenv_t *host_environment;

// Host services use the host FP state. Restore guest FP state after a callback,
// including nested host-to-guest calls from NVN hooks.
#define HOST_RESULT(c, expression) ({ \
    fenv_t guest_environment; fegetenv(&guest_environment); \
    fesetenv(host_environment); int host_result = (expression); \
    fesetenv(&guest_environment); rt_fpcr((c), (c)->fpcr); host_result; \
})

static void halt_if(int stop) { if (stop) longjmp(*escape, 1); }
static void call(Cpu *c) { halt_if(HOST_RESULT(c, sw_host_call(c))); }
static void svc(Cpu *c, uint32_t imm, uint64_t pc) { halt_if(HOST_RESULT(c, sw_host_svc(c, imm, pc))); }
static void trap(Cpu *c, uint32_t kind, uint32_t imm, uint64_t pc) { halt_if(HOST_RESULT(c, sw_host_trap(c, kind, imm, pc))); }
static uint64_t ticks(void) { return sw_host_ticks(active); }
static void *resolve_hle(uint64_t pc) { return sw_host_hle(active, pc) ? (void *)(uintptr_t)pc : NULL; }
static void call_hle(void *h, Cpu *c) { (void)h; call(c); }

void sw_initialize(void) {
    RtHost host = {call, svc, trap, ticks, resolve_hle, call_hle};
    nx_rt_init(&host);
    for (size_t i = 0; i < sw_module_count(); ++i) {
        const SwModule *m = sw_module_at(i);
        if (nx_rt_add_module(m->addresses, m->functions, *m->count)) __builtin_trap();
    }
}

int sw_function_enter(Cpu *c, uint64_t address) {
    c->pc = address;
    int skip = unhooked == address;
    if (skip) unhooked = 0;
    // The integer-only guard preserves guest FP state and validates code on
    // every entry. Real callbacks still cross the full host FP/register ABI.
    if (sw_host_entry_is_plain(c, address, skip)) return 0;
    int result = HOST_RESULT(c, sw_host_enter(c, address, skip));
    halt_if(result == 2);
    return result == 1;
}

void sw_poll(Cpu *c) {
    if (--poll_budget) return;
    poll_budget = 2048;
    halt_if(HOST_RESULT(c, sw_host_poll(c)));
}

void sw_enter(Cpu *c, uintptr_t memory_base, uint64_t skip) {
    jmp_buf stop;
    jmp_buf *previous_escape = escape;
    Cpu *previous_active = active;
    uintptr_t previous_base = sw_guest_memory_base;
    uint64_t previous_unhooked = unhooked;
    unsigned previous_budget = poll_budget;
    const fenv_t *previous_environment = host_environment;
    fenv_t environment;
    fegetenv(&environment);
    host_environment = &environment;
    escape = &stop; active = c; unhooked = skip; poll_budget = 2048;
    sw_guest_memory_base = memory_base;
    rt_fpcr(c, c->fpcr);
    if (!setjmp(stop)) rt_dispatch(c);
    escape = previous_escape; active = previous_active;
    sw_guest_memory_base = previous_base; unhooked = previous_unhooked; poll_budget = previous_budget;
    host_environment = previous_environment;
    fesetenv(&environment);
}
