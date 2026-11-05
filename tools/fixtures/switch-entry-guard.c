// Original host/guest FP-boundary fixture; uses the actual exported bridge.
#include "bridge.c"
#include <assert.h>
#include <stdio.h>

static unsigned checks, callbacks, needs_host, host_csr, guest_csr;
void nx_rt_init(const RtHost *host) { (void)host; }
int nx_rt_add_module(const uint64_t *a, const GuestFn *f, uint64_t n) { return 0; }
size_t sw_module_count(void) { return 0; }
const SwModule *sw_module_at(size_t i) { return NULL; }
int sw_host_call(Cpu *c) { return 0; }
int sw_host_svc(Cpu *c, uint32_t i, uint64_t pc) { return 0; }
int sw_host_trap(Cpu *c, uint32_t k, uint32_t i, uint64_t pc) { return 0; }
int sw_host_poll(Cpu *c) { return 0; }
uint64_t sw_host_ticks(Cpu *c) { return 0; }
int sw_host_hle(Cpu *c, uint64_t pc) { return 0; }
int sw_host_entry_is_plain(Cpu *c, uint64_t pc, int skip) {
    assert(__builtin_ia32_stmxcsr() == guest_csr);
    ++checks;
    return !needs_host;
}
int sw_host_enter(Cpu *c, uint64_t pc, int skip) {
    assert(needs_host);
    assert(__builtin_ia32_stmxcsr() == host_csr);
    assert(c->fpcr == (1u << 24));
    ++callbacks;
    c->x[0] = 42;
    c->fpcr = 0; // A real callback's FPCR update must reach the guest.
    return 0;
}
void RT_CC rt_dispatch(Cpu *c) {
    guest_csr = __builtin_ia32_stmxcsr() | 0x21; // Sticky invalid/inexact.
    __builtin_ia32_ldmxcsr(guest_csr);
    for (unsigned i = 0; i < 10000; ++i) assert(sw_function_enter(c, 0x8000) == 0);
    assert(checks == 10000 && callbacks == 0);
    assert(__builtin_ia32_stmxcsr() == guest_csr && c->fpsr == 0x77);
    needs_host = 1;
    assert(sw_function_enter(c, 0x8080) == 0);
    assert(checks == 10001 && callbacks == 1 && c->x[0] == 42);
    assert(__builtin_ia32_stmxcsr() == (guest_csr & ~0x8040u));
}
int main(void) {
    __builtin_ia32_ldmxcsr(__builtin_ia32_stmxcsr() & ~0x807fu);
    host_csr = __builtin_ia32_stmxcsr();
    Cpu c = {0}; c.fpcr = 1u << 24; c.fpsr = 0x77;
    sw_enter(&c, 0, UINT64_MAX);
    assert(__builtin_ia32_stmxcsr() == host_csr);
    puts("plain entries: 10000; callbacks: 1; FP state preserved");
    return 0;
}
