// Bounded CPU development harness. No Horizon services or instruction fallback.
#include "cpu.h"
#include "layout.h"
#include <inttypes.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

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
extern void nx_rt_enter(Cpu *);
extern const uint64_t guest_fn_addrs[], guest_fn_count;
extern const GuestFn guest_fn_ptrs[];
extern int switch_asset_matches(const char *);

static jmp_buf stopped;
static Cpu cpu;
static unsigned char *memory, *original_text;
static _Alignas(16) unsigned char stack[0x10000];
static uint64_t native_entries, miss_pc;
static const char *failure = "";

static void fail(const char *reason, uint64_t pc) {
    failure = reason; miss_pc = pc; longjmp(stopped, 1);
}

void switch_code_guard(Cpu *c) {
    if (memcmp(memory + TEXT_OFFSET, original_text, TEXT_SIZE))
        fail("changed-code", c->pc);
    ++native_entries;
}

static void missing(Cpu *c) { fail("missing-native-target", c->pc); }
static void svc(Cpu *c, uint32_t imm, uint64_t pc) {
    (void)c; (void)imm; fail("unsupported-svc", pc);
}
static void trap(Cpu *c, uint32_t kind, uint32_t imm, uint64_t pc) {
    (void)c; (void)imm; fail(kind ? "unsupported-instruction" : "guest-breakpoint", pc);
}
static uint64_t ticks(void) { fail("unsupported-timing-service", cpu.pc); return 0; }
static void *resolve_hle(uint64_t pc) { (void)pc; return NULL; }
static void call_hle(void *h, Cpu *c) { (void)h; missing(c); }

static int report(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "cannot write execution report\n"); return 2; }
    fprintf(f, "{\"schema\":\"decomp.wtf.switch-cpu-run/v1\",\"output_kind\":\"cpu-probe\","
        "\"input_sha256\":\"%s\",\"status\":\"%s\",\"failure\":\"%s\","
        "\"miss_pc\":%" PRIu64 ",\"native_function_entries\":%" PRIu64 ","
        "\"interpreter_instructions\":0,\"runtime_compilation\":false,"
        "\"graphics\":false,\"retail\":false,\"x\":[",
        INPUT_SHA256, failure[0] ? "failed" : "passed", failure, miss_pc, native_entries);
    for (unsigned i = 0; i < 31; ++i) fprintf(f, "%s%" PRIu64, i ? "," : "", cpu.x[i]);
    fprintf(f, "],\"nzcv\":%" PRIu64 ",\"v\":[", cpu.nzcv);
    for (unsigned i = 0; i < 32; ++i)
        fprintf(f, "%s[%" PRIu64 ",%" PRIu64 "]", i ? "," : "",
            (uint64_t)cpu.v[i], (uint64_t)(cpu.v[i] >> 64));
    fprintf(f, "],\"data_hex\":\"");
    if (memory) for (unsigned i = 0; i < DATA_SIZE && i < 64; ++i)
        fprintf(f, "%02x", memory[DATA_OFFSET + i]);
    fprintf(f, "\"}\n");
    int bad = ferror(f); if (fclose(f)) bad = 1;
    return bad ? 2 : (failure[0] ? 1 : 0);
}

int main(int argc, char **argv) {
    if (argc < 3 || argc > 4 || (argc == 4 && strcmp(argv[3], "--tamper-code") && strcmp(argv[3], "--missing-target"))) {
        fprintf(stderr, "usage: switch_probe image.bin report.json [--tamper-code|--missing-target]\n"); return 2;
    }
    if (!switch_asset_matches(argv[1])) { failure = "asset-identity-mismatch"; return report(argv[2]); }
#ifdef _WIN32
    memory = VirtualAlloc((void *)(uintptr_t)IMAGE_BASE, IMAGE_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (memory && memory != (void *)(uintptr_t)IMAGE_BASE) { VirtualFree(memory, 0, MEM_RELEASE); memory = NULL; }
#else
    void *mapped = mmap((void *)(uintptr_t)IMAGE_BASE, IMAGE_SIZE, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapped == MAP_FAILED) mapped = NULL;
    if (mapped && mapped != (void *)(uintptr_t)IMAGE_BASE) { munmap(mapped, IMAGE_SIZE); mapped = NULL; }
    memory = mapped;
#endif
    if (!memory) { failure = "guest-address-unavailable"; return report(argv[2]); }
    FILE *file = fopen(argv[1], "rb");
    if (!file) { failure = "missing-image"; return report(argv[2]); }
    size_t read = fread(memory, 1, IMAGE_SIZE, file); int bad = ferror(file); fclose(file);
    if (read != IMAGE_SIZE || bad) { failure = "image-read-failed"; return report(argv[2]); }
    original_text = malloc(TEXT_SIZE);
    if (!original_text) { failure = "allocation-failed"; return report(argv[2]); }
    memcpy(original_text, memory + TEXT_OFFSET, TEXT_SIZE);
    if (argc == 4 && !strcmp(argv[3], "--tamper-code")) memory[TEXT_OFFSET] ^= 1;
    RtHost host = {missing, svc, trap, ticks, resolve_hle, call_hle};
    nx_rt_init(&host);
    if (nx_rt_add_module(guest_fn_addrs, guest_fn_ptrs, guest_fn_count)) {
        failure = "module-registration-failed"; return report(argv[2]);
    }
    cpu.pc = IMAGE_ENTRY;
    if (argc == 4 && !strcmp(argv[3], "--missing-target")) cpu.pc = IMAGE_BASE + IMAGE_SIZE + 4;
    cpu.sp = (uintptr_t)(stack + sizeof stack);
    cpu.excl_addr = UINT64_MAX;
    if (!setjmp(stopped)) nx_rt_enter(&cpu);
    int result = report(argv[2]);
    free(original_text);
#ifdef _WIN32
    VirtualFree(memory, 0, MEM_RELEASE);
#else
    munmap(memory, IMAGE_SIZE);
#endif
    return result;
}
