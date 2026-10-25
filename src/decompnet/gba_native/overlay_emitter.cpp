// SPDX-License-Identifier: MIT
// Analyze each observed ROM-to-RAM copy in its own address-space view.
#include "analysis/functions.h"
#include "codegen/c_emitter.h"
#include "config/game_config.h"
#include <fstream>
#include <iterator>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <tuple>

int main(int argc, char** argv) { try {
    if (argc != 4) throw std::runtime_error("expected ROM, overlay configuration and output C file");
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) throw std::runtime_error("cannot read overlay ROM");
    const std::vector<uint8_t> rom{std::istreambuf_iterator<char>(input), {}};
    const auto config = anygba::config::load_game_config(argv[2]);
    std::ostringstream functions, table;
    unsigned count = 0;
    std::set<std::tuple<uint32_t, unsigned, uint32_t, uint32_t, uint32_t>> seen;
    for (const auto& copy : config.ram_code) {
        anygba::analysis::Image image(rom);
        image.add_region(copy.region);
        anygba::analysis::DiscoveryOptions options;
        options.scan_literal_pools = false;
        options.skip.push_back({0x08000000, 0x0e000000});
        options.entries.push_back({copy.region.ram_dst, copy.mode, anygba::analysis::EntrySource::MissLog});
        for (const auto& entry : config.entries)
            if (entry.addr >= copy.region.ram_dst && entry.addr < copy.region.ram_dst + copy.region.size)
                options.entries.push_back(entry);
        const auto discovery = anygba::analysis::discover(image, options);
        for (const auto& [address, fn] : discovery.functions) {
            const auto footprint = anygba::codegen::code_footprint(fn, &image);
            if (fn.hit_undefined || footprint.end <= footprint.begin ||
                footprint.begin < copy.region.ram_dst || footprint.end > copy.region.ram_dst + copy.region.size)
                continue;
            const auto source = image.rom_offset(footprint.begin, footprint.end - footprint.begin);
            if (!source) continue;
            const unsigned thumb = fn.mode == anygba::analysis::Mode::Thumb;
            if (!seen.emplace(address, thumb, *source, footprint.begin, footprint.end).second) continue;
            const std::string name = "gba_overlay_" + std::to_string(count++);
            anygba::codegen::EmitOptions emit;
            emit.image = &image;
            emit.name = name;
            // Calls always use runtime dispatch: callees may have been replaced in RAM.
            functions << anygba::codegen::emit_function(fn, emit) << '\n';
            if (count > 1) table << ',';
            table << "[" << address << "," << thumb << ",\"" << name << "\","
                  << footprint.begin << "," << footprint.end << "," << (0x08000000u + *source) << "]";
        }
    }
    std::ofstream output(argv[3], std::ios::binary);
    output << "/* ROM-derived native overlays; keep private with the generated game. */\n"
              "#include <anygba/cpu.h>\n\n" << functions.str();
    output.close();
    if (!output) throw std::runtime_error("cannot write native overlays");
    std::cout << '[' << table.str() << "]\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
