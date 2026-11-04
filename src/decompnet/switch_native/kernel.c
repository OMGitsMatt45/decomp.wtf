// Bounded, single-main-thread Horizon boundary. Register and HIPC/CMIF layouts
// follow Kirikae's MIT horizon.rs/ipc.rs/services/sm.rs at the pinned revision.
// Unsupported services and command shapes stop instead of returning fake success.
#include "runtime_api.h"
#include <stdio.h>

uint64_t switch_heap_size, switch_svc_counts[128], switch_ipc_calls;
uint64_t switch_debug_bytes, switch_last_svc, switch_last_ipc;
static uint64_t current_pc;
static unsigned char kinds[32], initialized[32];
static unsigned next_handle;
enum { SM = 1, SETTINGS = 2 };
#define INVALID_HANDLE 0xe401ull

static uint32_t u32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (i * 8));
}
static void put64(unsigned char *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }
static void *memory(uint64_t address, uint64_t size, int writable) {
    void *p = switch_memory(address, size, writable);
    if (!p) switch_fail("invalid-guest-memory", current_pc);
    return p;
}
static unsigned handle(unsigned kind) {
    if (next_handle >= 32) switch_fail("handle-table-exhausted", current_pc);
    unsigned slot = next_handle++;
    kinds[slot] = (unsigned char)kind;
    return 0x100 + slot;
}
static int slot(uint64_t h) {
    return h >= 0x100 && h < 0x120 && kinds[h - 0x100] ? (int)(h - 0x100) : -1;
}

static void reply(unsigned char *msg, uint64_t size, uint32_t token,
                  unsigned moved, const unsigned char *data, unsigned count) {
    unsigned start = moved ? 16 : 8;
    unsigned at = (start + 15) & ~15u;
    unsigned words = (16 + 16 + count + 3) / 4;
    if (start + words * 4 > size) switch_fail("ipc-response-too-large", current_pc);
    memset(msg, 0, (size_t)size);
    put32(msg + 4, words | (moved ? 0x80000000u : 0));
    if (moved) { put32(msg + 8, 1u << 5); put32(msg + 12, moved); }
    put32(msg + at, 0x4f434653); // SFCO
    put32(msg + at + 12, token);
    if (count) memcpy(msg + at + 16, data, count);
}

static uint64_t ipc(uint64_t h, uint64_t address, uint64_t size) {
    int index = slot(h);
    if (index < 0) return INVALID_HANDLE;
    if (size < 0x20 || size > 0x100) switch_fail("unsupported-ipc-buffer-size", current_pc);
    unsigned char *msg = memory(address, size, 1);
    uint32_t h0 = u32(msg), h1 = u32(msg + 4);
    unsigned kind = h0 & 0xffff, start = 8;
    if (h0 & 0xffff0000u || h1 & 0x7ffffc00u)
        switch_fail("unsupported-ipc-descriptors", current_pc);
    if (h1 & 0x80000000u) {
        uint32_t special = u32(msg + 8);
        if (special & ~1u) switch_fail("unsupported-ipc-handles", current_pc);
        start = 12 + ((special & 1) ? 8 : 0);
    }
    unsigned end = start + (h1 & 0x3ff) * 4;
    unsigned at = (start + 15) & ~15u;
    if (end > size || end < at + 16 || u32(msg + at) != 0x49434653 || u32(msg + at + 4) > 1)
        switch_fail("malformed-ipc", current_pc);
    uint32_t command = u32(msg + at + 8), token = u32(msg + at + 12);
    switch_last_ipc = command;
    ++switch_ipc_calls;
    if ((kind == 5 || kind == 7) && command == 3) {
        unsigned char data[2] = {0, 0}; // No pointer-buffer descriptors are supported yet.
        reply(msg, size, token, 0, data, 2);
        return 0;
    }
    if (kind != 4 && kind != 6) switch_fail("unsupported-ipc-type", current_pc);
    if (kinds[index] == SM && command == 0) {
        initialized[index] = 1;
        reply(msg, size, token, 0, NULL, 0);
    } else if (kinds[index] == SM && command == 1) {
        if (!initialized[index] || end < at + 24) switch_fail("malformed-sm-request", current_pc);
        uint64_t name = u64(msg + at + 16);
        if (name != 0x746573ull) switch_fail("unsupported-service", current_pc); // "set"
        reply(msg, size, token, handle(SETTINGS), NULL, 0);
    } else if (kinds[index] == SETTINGS && command == 0) {
        // set:GetLanguageCode, fixed development environment: en-US.
        const unsigned char language[8] = {'e', 'n', '-', 'U', 'S', 0, 0, 0};
        reply(msg, size, token, 0, language, 8);
    } else {
        switch_fail("unsupported-ipc-command", current_pc);
    }
    return 0;
}

void switch_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    current_pc = pc;
    switch_last_svc = imm;
    if (imm >= 128) switch_fail("unsupported-svc", pc);
    ++switch_svc_counts[imm];
    switch (imm) {
    case 0x01: { // SetHeapSize: size in x1; Result/x1 address out.
        uint64_t size = c->x[1];
        if (size % 0x200000) { c->x[0] = 0xca01; c->x[1] = 0; break; }
        if (size > HEAP_SIZE) { c->x[0] = 0x10801; c->x[1] = 0; break; }
        // This development heap can grow, but never silently discard live state.
        if (size < switch_heap_size) switch_fail("unsupported-heap-shrink", pc);
        switch_heap_size = size;
        c->x[0] = 0; c->x[1] = HEAP_BASE;
        break;
    }
    case 0x07: case 0x0a: switch_exit(); // ExitProcess / the only guest thread.
    case 0x10: c->x[0] = 0; break; // One logical CPU in this bounded runtime.
    case 0x16: { // CloseHandle
        int index = slot(c->x[0]);
        if (index < 0) c->x[0] = INVALID_HANDLE;
        else { kinds[index] = 0; c->x[0] = 0; }
        break;
    }
    case 0x1e: c->x[0] = switch_ticks(); break;
    case 0x1f: { // ConnectToNamedPort
        unsigned char name[12] = {0};
        unsigned i;
        for (i = 0; i < sizeof name; ++i) {
            name[i] = *(unsigned char *)memory(c->x[1] + i, 1, 0);
            if (!name[i]) break;
        }
        if (i == sizeof name || strcmp((char *)name, "sm:")) switch_fail("unsupported-named-port", pc);
        c->x[0] = 0; c->x[1] = handle(SM);
        break;
    }
    case 0x21: c->x[0] = ipc(c->x[0], c->tpidrro, 0x100); break;
    case 0x22: { // SendSyncRequestWithUserBuffer
        uint64_t result = ipc(c->x[2], c->x[0], c->x[1]);
        c->x[0] = result; break;
    }
    case 0x25: // GetThreadId, main handle or current-thread pseudo handle.
        if (c->x[1] != 1 && c->x[1] != 0xffff8000u) { c->x[0] = INVALID_HANDLE; c->x[1] = 0; }
        else { c->x[0] = 0; c->x[1] = 0x51; }
        break;
    case 0x27: { // OutputDebugString
        uint64_t count = c->x[1];
        if (count > 4096) switch_fail("debug-message-too-large", pc);
        const void *bytes = memory(c->x[0], count, 0);
        if (fwrite(bytes, 1, (size_t)count, stderr) != count) switch_fail("debug-output-failed", pc);
        switch_debug_bytes += count;
        c->x[0] = 0;
        break;
    }
    default: switch_fail("unsupported-svc", pc);
    }
}
