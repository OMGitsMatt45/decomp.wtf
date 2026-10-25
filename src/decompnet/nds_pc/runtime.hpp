// SPDX-License-Identifier: MIT. Original decomp.wtf experimental DS runtime.
#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace nds {
constexpr uint32_t stop_pc = 0xfffffffcu;
struct Cpu {
    uint32_t r[16]{};
    uint32_t pc = 0;
    unsigned id = 0;
    bool thumb = false, halted = false;
    bool n = false, z = false, carry = false, v = false;
};
struct Shift { uint32_t value; bool carry; };
Shift shift(uint32_t value, unsigned kind, unsigned amount, bool carry, bool by_register);
uint32_t add(Cpu&, uint32_t a, uint32_t b, bool carry_in, bool flags);
void logic_flags(Cpu&, uint32_t value, bool carry);
bool condition(const Cpu&, unsigned condition);
uint32_t sign_extend(uint32_t value, unsigned bits);
struct Module {
    const char* name;
    unsigned cpu;
    int overlay;
    uint32_t address, size, bss_address, bss_size;
    const char* asset;
};
struct CodeRange { unsigned cpu; int overlay; uint32_t address, size; const uint8_t* expected; };
extern const Module modules[];
extern const unsigned module_count;
extern const CodeRange code_ranges[];
extern const unsigned code_range_count;
extern const uint32_t entries[2], stacks[2];
extern const uint32_t observations[];
extern const unsigned observation_count;
extern const uint32_t save_address, save_size;

class Runtime {
    std::vector<uint8_t> ram_, shared_, iwram_;
    std::filesystem::path assets_;
    uint8_t* memory(uint32_t address, unsigned size);
    void writable(uint32_t address, unsigned size);
    void load(const Module&);
public:
    Cpu cpu[2];
    int active_overlay[2]{-1,-1};
    std::vector<unsigned> overlay_loads;
    uint64_t steps = 0;
    explicit Runtime(std::filesystem::path assets);
    uint8_t read8(uint32_t address);
    uint16_t read16(uint32_t address);
    uint32_t read32(uint32_t address);
    void write8(uint32_t address, uint32_t value);
    void write16(uint32_t address, uint32_t value);
    void write32(uint32_t address, uint32_t value);
    void branch(Cpu&, uint32_t target, bool exchange);
    void load_overlay(unsigned processor, unsigned id);
    void load_save(const std::filesystem::path&);
    void write_save(const std::filesystem::path&);
    void run(uint64_t max_steps);
};
bool dispatch_arm9(Runtime&, Cpu&);
bool dispatch_arm7(Runtime&, Cpu&);
bool service(Runtime&, Cpu&);
std::string hex(uint32_t address);
}
