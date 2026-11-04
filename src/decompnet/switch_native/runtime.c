// Host-linked module/service development runtime; no instruction fallback.
#include "runtime_api.h"
#include <inttypes.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

extern int switch_asset_matches_expected(const char *, const char *);
typedef struct Region { uint64_t base, size, writable; void *memory; } Region;
static Region regions[MODULE_COUNT + 3];
static unsigned char *original_text[MODULE_COUNT];
static uint64_t module_entries[MODULE_COUNT];
static Cpu cpu;
static jmp_buf stopped;
static const char *failure = "";
static uint64_t miss_pc, native_entries, initializers_run;
static int exited;

void switch_fail(const char *why, uint64_t pc) { failure = why; miss_pc = pc; longjmp(stopped, 1); }
void switch_exit(void) { exited = 1; longjmp(stopped, 2); }

void *switch_memory(uint64_t address, uint64_t size, int writable) {
    if (size > UINT64_MAX - address) return NULL;
    for (unsigned i = 0; i < MODULE_COUNT + 3; ++i) {
        Region *r = &regions[i];
        uint64_t limit = r->base == HEAP_BASE ? switch_heap_size : r->size;
        if (r->memory && address >= r->base && address - r->base <= limit &&
            size <= limit - (address - r->base) && (!writable || address >= r->writable))
            return (unsigned char *)r->memory + (address - r->base);
    }
    return NULL;
}

void switch_code_guard(Cpu *c) {
    for (unsigned i = 0; i < MODULE_COUNT; ++i) {
        const SwitchModule *m = &switch_modules[i];
        if (c->pc >= m->base && c->pc - m->base < m->size) {
            if (memcmp((unsigned char *)regions[i].memory + m->text_offset, original_text[i], m->text_size))
                switch_fail("changed-code", c->pc);
            ++native_entries; ++module_entries[i];
            return;
        }
    }
    switch_fail("missing-native-target", c->pc);
}

uint64_t switch_ticks(void) {
#ifdef _WIN32
    LARGE_INTEGER count, frequency;
    if (!QueryPerformanceCounter(&count) || !QueryPerformanceFrequency(&frequency))
        switch_fail("host-clock-failed", cpu.pc);
    return (uint64_t)((long double)count.QuadPart * 19200000 / frequency.QuadPart);
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) switch_fail("host-clock-failed", cpu.pc);
    return (uint64_t)now.tv_sec * 19200000 + (uint64_t)now.tv_nsec * 19200000 / 1000000000;
#endif
}
static void missing(Cpu *c) { switch_fail("missing-native-target", c->pc); }
static void trap(Cpu *c, uint32_t kind, uint32_t imm, uint64_t pc) {
    (void)c; (void)imm; switch_fail(kind ? "unsupported-instruction" : "guest-breakpoint", pc);
}
static void *resolve_hle(uint64_t pc) { (void)pc; return NULL; }
static void call_hle(void *h, Cpu *c) { (void)h; missing(c); }

static int map(unsigned slot, uint64_t base, uint64_t size, uint64_t writable) {
    void *memory;
#ifdef _WIN32
    memory = VirtualAlloc((void *)(uintptr_t)base, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (memory && memory != (void *)(uintptr_t)base) { VirtualFree(memory, 0, MEM_RELEASE); memory = NULL; }
#else
    memory = mmap((void *)(uintptr_t)base, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) memory = NULL;
    if (memory && memory != (void *)(uintptr_t)base) { munmap(memory, size); memory = NULL; }
#endif
    regions[slot] = (Region){base, size, writable, memory};
    return memory != NULL;
}

static void invoke(uint64_t entry) {
    memset(&cpu, 0, sizeof cpu);
    cpu.pc = entry; cpu.sp = STACK_BASE + STACK_SIZE;
    cpu.tpidr = cpu.tpidrro = TLS_BASE;
    cpu.x[1] = 1; // Main-thread handle, not a guest dynamic-linker argument.
    cpu.excl_addr = UINT64_MAX;
    nx_rt_enter(&cpu);
}

static int report(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "cannot write Switch runtime report\n"); return 2; }
    fprintf(f, "{\"schema\":\"decomp.wtf.switch-runtime-run/v1\",\"output_kind\":\"cpu-probe\","
        "\"startup_model\":\"host-linked-main\",\"input_sha256\":\"%s\",\"status\":\"%s\","
        "\"failure\":\"%s\",\"miss_pc\":%" PRIu64 ",\"last_svc\":%" PRIu64 ",\"last_ipc\":%" PRIu64 ","
        "\"native_function_entries\":%" PRIu64 ",\"initializers_run\":%" PRIu64 ",\"exited\":%s,"
        "\"interpreter_instructions\":0,\"runtime_compilation\":false,\"graphics\":false,\"retail\":false,"
        "\"heap_size\":%" PRIu64 ",\"ipc_calls\":%" PRIu64 ",\"debug_bytes\":%" PRIu64 ",\"svc_counts\":{",
        INPUT_SHA256, failure[0] ? "failed" : "passed", failure, miss_pc, switch_last_svc, switch_last_ipc,
        native_entries, initializers_run, exited ? "true" : "false", switch_heap_size, switch_ipc_calls, switch_debug_bytes);
    unsigned written = 0;
    for (unsigned i = 0; i < 128; ++i) if (switch_svc_counts[i])
        fprintf(f, "%s\"%u\":%" PRIu64, written++ ? "," : "", i, switch_svc_counts[i]);
    fprintf(f, "},\"x\":[");
    for (unsigned i = 0; i < 31; ++i) fprintf(f, "%s%" PRIu64, i ? "," : "", cpu.x[i]);
    fprintf(f, "],\"modules\":[");
    for (unsigned i = 0; i < MODULE_COUNT; ++i) {
        const SwitchModule *m = &switch_modules[i];
        fprintf(f, "%s{\"name\":\"%s\",\"base\":%" PRIu64 ",\"native_entries\":%" PRIu64 ",\"data_hex\":\"",
                i ? "," : "", m->name, m->base, module_entries[i]);
        if (regions[i].memory) for (unsigned j = 0; j < m->data_size && j < 128; ++j)
            fprintf(f, "%02x", ((unsigned char *)regions[i].memory)[m->data_offset + j]);
        fprintf(f, "\"}");
    }
    fprintf(f, "]}\n");
    int bad = ferror(f); if (fclose(f)) bad = 1;
    return bad ? 2 : failure[0] ? 1 : 0;
}

int main(int argc, char **argv) {
    if (argc < 3 || argc > 4 || (argc == 4 && strcmp(argv[3], "--tamper-code") && strcmp(argv[3], "--missing-target"))) {
        fprintf(stderr, "usage: switch_runtime assets-directory report.json [--tamper-code|--missing-target]\n"); return 2;
    }
    for (unsigned i = 0; i < MODULE_COUNT; ++i) {
        char path[8192];
        int count = snprintf(path, sizeof path, "%s/%s", argv[1], switch_modules[i].file);
        if (count < 0 || count >= sizeof path || !switch_asset_matches_expected(path, switch_modules[i].sha256)) {
            failure = "asset-identity-mismatch"; return report(argv[2]);
        }
    }
    for (unsigned i = 0; i < MODULE_COUNT; ++i) {
        const SwitchModule *m = &switch_modules[i];
        if (!map(i, m->base, m->size, m->base + m->data_offset)) { failure = "guest-address-unavailable"; break; }
        char path[8192]; snprintf(path, sizeof path, "%s/%s", argv[1], m->file);
        FILE *file = fopen(path, "rb");
        if (!file) { failure = "missing-image"; break; }
        size_t count = fread(regions[i].memory, 1, m->size, file);
        int bad = ferror(file); fclose(file);
        if (count != m->size || bad) { failure = "image-read-failed"; break; }
        original_text[i] = malloc(m->text_size);
        if (!original_text[i]) { failure = "allocation-failed"; break; }
        memcpy(original_text[i], (unsigned char *)regions[i].memory + m->text_offset, m->text_size);
    }
    if (!failure[0] && (!map(MODULE_COUNT, STACK_BASE, STACK_SIZE, STACK_BASE) ||
        !map(MODULE_COUNT + 1, HEAP_BASE, HEAP_SIZE, HEAP_BASE) ||
        !map(MODULE_COUNT + 2, TLS_BASE, 0x1000, TLS_BASE))) failure = "guest-address-unavailable";
    if (!failure[0]) {
        RtHost host = {missing, switch_svc, trap, switch_ticks, resolve_hle, call_hle};
        nx_rt_init(&host);
        for (unsigned i = 0; i < MODULE_COUNT; ++i) {
            const SwitchModule *m = &switch_modules[i];
            if (nx_rt_add_module(m->addresses, m->functions, *m->count)) failure = "module-registration-failed";
        }
        if (argc == 4 && !strcmp(argv[3], "--tamper-code"))
            ((unsigned char *)regions[MODULE_COUNT - 1].memory)[switch_modules[MODULE_COUNT - 1].text_offset] ^= 1;
        if (!failure[0] && !setjmp(stopped)) {
            for (uint64_t i = 0; i < switch_initializer_count; ++i) {
                invoke(switch_initializers[i]); ++initializers_run;
            }
            invoke(argc == 4 && !strcmp(argv[3], "--missing-target") ? 0x7fffffffffffull : IMAGE_ENTRY);
        }
    }
    int result = report(argv[2]);
    for (unsigned i = 0; i < MODULE_COUNT; ++i) free(original_text[i]);
    for (unsigned i = 0; i < MODULE_COUNT + 3; ++i) if (regions[i].memory) {
#ifdef _WIN32
        VirtualFree(regions[i].memory, 0, MEM_RELEASE);
#else
        munmap(regions[i].memory, regions[i].size);
#endif
    }
    return result;
}
