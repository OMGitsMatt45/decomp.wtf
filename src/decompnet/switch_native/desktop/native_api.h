#pragma once
#include "cpu.h"
#include <stddef.h>

typedef struct SwModule {
    const char *name, *file, *sha256;
    uint64_t base, size, text_offset, text_size, ro_offset, ro_size, data_offset, data_size, bss_size;
    const uint64_t *addresses;
    const GuestFn *functions;
    const uint64_t *count;
} SwModule;

size_t sw_module_count(void);
const SwModule *sw_module_at(size_t index);
const uint64_t *sw_initializers(size_t *count);
const uint64_t *sw_sdk_initializers(size_t *count);
const uint64_t *sw_main_initializers(size_t *count);
const uint64_t *sw_sdk_finalizers(size_t *count);
uint64_t sw_sdk_startup(void);
uint64_t sw_entry(void);
uint64_t sw_stack_size(void);
uint64_t sw_system_resource_size(void);
uint64_t sw_title_id(void);
const char *sw_input_sha256(void);
const char *sw_backend_revision(void);
const char *sw_romfs_sha256(void);

void sw_initialize(void);
void sw_enter(Cpu *c, uintptr_t memory_base, uint64_t unhooked);
int sw_function_enter(Cpu *c, uint64_t address);
void sw_poll(Cpu *c);

int sw_host_enter(Cpu *, uint64_t, int);
int sw_host_entry_is_plain(Cpu *, uint64_t, int);
int sw_host_call(Cpu *);
int sw_host_svc(Cpu *, uint32_t, uint64_t);
int sw_host_trap(Cpu *, uint32_t, uint32_t, uint64_t);
int sw_host_poll(Cpu *);
uint64_t sw_host_ticks(Cpu *);
int sw_host_hle(Cpu *, uint64_t);
int switch_native_main(int argc, char **argv);
