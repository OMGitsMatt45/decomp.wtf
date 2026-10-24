// CC0 original, headless CPU comparison host. No window, BIOS or game is loaded.
#include "ps2_runtime.h"
#include "original_program.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

static uint64_t number(const char *text) { return std::stoull(text, nullptr, 16); }

int main(int argc, char **argv) {
    try {
        if (argc != 8 && argc != 9) throw std::runtime_error("entry aLow aHigh bLow bHigh output mode [tamper]");
        auto runtime = std::make_unique<PS2Runtime>();
        if (!runtime->memory().initialize()) throw std::runtime_error("memory initialization failed");
        runtime->setMissingFunctionPolicy(PS2Runtime::MissingFunctionPolicy::Stop);
        auto &ctx = runtime->cpu();
        auto *ram = runtime->memory().getRDRAM();
        std::memcpy(ram + 0x100000, original_program, sizeof(original_program));
        for (unsigned n = 0; n < 64; ++n) ram[0x200000 + n] = static_cast<uint8_t>(n);
        for (unsigned n = 0; n < 32; ++n)
            ctx.r[n] = _mm_set_epi64x(static_cast<int64_t>(0xA500000000000000ull + n), 0x51000000ull + n);
        ctx.r[0] = _mm_setzero_si128();
        ctx.r[4] = _mm_set_epi64x(number(argv[3]), number(argv[2]));
        ctx.r[5] = _mm_set_epi64x(number(argv[5]), number(argv[4]));
        ctx.r[6] = _mm_set_epi64x(0, 0x200000);
        ctx.r[25] = _mm_set_epi64x(0, original_helper);
        ctx.r[29] = _mm_set_epi64x(0, 0x1FFF000);
        ctx.r[31] = _mm_set_epi64x(0, 0x1F00000);
        ctx.hi = 0x12345678; ctx.lo = 0xABCDEF01;
        ctx.hi1 = 0x87654321; ctx.lo1 = 0x10FEDCBA;
        ctx.pc = static_cast<uint32_t>(number(argv[1]));
        if (argc == 9) ram[0x100000] ^= 1;
        std::ofstream out(argv[6]);
        if (!out) throw std::runtime_error("cannot open output");
        // This guard belongs to the assessment host; the upstream dispatch
        // table itself does not validate bytes of newly loaded overlays.
        if (std::memcmp(ram + 0x100000, original_program, sizeof(original_program)) != 0) {
            out << "{\"native_rejected\":true}\n";
            return 0;
        }
        if (!runtime->hasFunction(ctx.pc)) throw std::runtime_error("entry missing from generated table");
        runtime->lookupFunction(ctx.pc)(ram, &ctx, runtime.get());
        if (runtime->isStopRequested()) throw std::runtime_error("guest dispatch stopped on an unresolved target");
        out << "{\"registers\":[";
        for (unsigned n = 0; n < 32; ++n) {
            uint64_t words[2]; std::memcpy(words, &ctx.r[n], sizeof(words));
            if (n) out << ',';
            out << '"' << std::hex << std::setfill('0') << std::setw(16) << words[1]
                << std::setw(16) << words[0] << '"';
        }
        out << "],\"hi\":" << std::dec << ctx.hi << ",\"lo\":" << ctx.lo
            << ",\"pc\":" << ctx.pc << ",\"memory\":\"";
        for (unsigned n = 0; n < 64; ++n)
            out << std::hex << std::setfill('0') << std::setw(2) << static_cast<unsigned>(ram[0x200000 + n]);
        out << "\"}\n";
        if (!out) throw std::runtime_error("cannot write result");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
