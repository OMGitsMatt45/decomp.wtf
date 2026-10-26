// SPDX-License-Identifier: MIT
// Analyze each observed ROM-to-RAM copy in its own address-space view.
#include "analysis/functions.h"
#include "analysis/cfg.h"
#include "codegen/c_emitter.h"
#include "config/game_config.h"
#include <fstream>
#include <iterator>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <tuple>

int main(int argc, char** argv) { try {
    if (argc != 4 && argc != 5) throw std::runtime_error("expected ROM, overlay configuration, output C file and optional bounded instruction regions");
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) throw std::runtime_error("cannot read overlay ROM");
    const std::vector<uint8_t> rom{std::istreambuf_iterator<char>(input), {}};
    const auto config = anygba::config::load_game_config(argv[2]);
    std::set<std::tuple<uint32_t,uint32_t,uint32_t>> bounded_regions,fragment_regions;
    if(argc==5) {
        std::ifstream list(argv[4]);if(!list)throw std::runtime_error("cannot read bounded instruction regions");
        uint32_t from,to,size;
        while(list>>from) {
            if(!(list>>to>>size))throw std::runtime_error("invalid bounded instruction region");
            bounded_regions.emplace(from,to,size);
        }
        if(!list.eof())throw std::runtime_error("invalid bounded instruction region list");
    }
    std::ostringstream table;
    const std::filesystem::path destination(argv[3]);
    std::ofstream shard;
    unsigned shard_index=0;
    std::size_t shard_bytes=0;
    const auto next_shard=[&]() {
        if(shard.is_open()){shard.close();if(!shard)throw std::runtime_error("cannot finish native overlay shard");}
        const auto path=shard_index ? destination.parent_path()/(destination.stem().string()+"_"+std::to_string(shard_index)+".c") : destination;
        ++shard_index;shard.open(path,std::ios::binary|std::ios::trunc);
        if(!shard)throw std::runtime_error("cannot create native overlay shard");
        shard<<"/* ROM-derived native overlays; keep private with the generated game. */\n#include <anygba/cpu.h>\n\n";
        shard_bytes=0;
    };
    next_shard();
    unsigned count = 0, rows = 0;
    std::set<std::tuple<uint32_t, unsigned, uint32_t, uint32_t, uint32_t>> seen;
    const auto emit_body=[&](const anygba::analysis::Function& fn,const anygba::analysis::Image& image,const auto& region) {
        const auto address=fn.entry;
        const auto footprint=anygba::codegen::code_footprint(fn,&image);
        if(fn.hit_undefined || footprint.end<=footprint.begin || footprint.begin<region.ram_dst ||
            footprint.end>region.ram_dst+region.size)return;
        const auto source=image.rom_offset(footprint.begin,footprint.end-footprint.begin);if(!source)return;
        const unsigned thumb=fn.mode==anygba::analysis::Mode::Thumb;
        if(!seen.emplace(address,thumb,*source,footprint.begin,footprint.end).second)return;
        const std::string name="gba_overlay_"+std::to_string(count++);
        anygba::codegen::EmitOptions emit;emit.image=&image;emit.name=name;
        const auto native_source=anygba::codegen::emit_function(fn,emit);
        if(shard_bytes && shard_bytes+native_source.size()>1024*1024)next_shard();
        shard<<native_source<<'\n';shard_bytes+=native_source.size()+1;
        for(const auto& [entry,instruction] : fn.insns) {
            if(rows++)table<<',';
            table<<"["<<entry<<","<<thumb<<",\""<<name<<(entry==address?"":"_resume")<<"\","
                 <<footprint.begin<<","<<footprint.end<<","<<(0x08000000u+*source)<<"]";
        }
    };
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
        const auto base=discovery.functions.find(copy.region.ram_dst);
        bool executable_prefix=false;
        for(auto pc=copy.region.ram_dst;std::uint64_t(pc)+2<=std::uint64_t(copy.region.ram_dst)+copy.region.size &&
                pc<copy.region.ram_dst+64;) {
            const auto op=anygba::analysis::decode_at(image,pc,copy.mode);if(!op.valid())break;
            if(op.cond==anygba::decode::Cond::AL &&
                (op.op==anygba::decode::Op::BX ||
                 (op.op==anygba::decode::Op::STM && op.rn==anygba::decode::kSP &&
                  (op.reglist&(1u<<anygba::decode::kLR)))))executable_prefix=true;
            pc=op.next();
        }
        if(bounded_regions.contains({copy.region.rom_src,copy.region.ram_dst,copy.region.size}) &&
            executable_prefix && base!=discovery.functions.end() && !base->second.hit_undefined &&
            base->second.has_exit && base->second.insns.size()>=4)
            fragment_regions.emplace(copy.region.rom_src,copy.region.ram_dst,copy.region.size);
        for (const auto& [address, fn] : discovery.functions) {
            // Calls use runtime dispatch: callees may have been replaced in RAM.
            emit_body(fn,image,copy.region);
        }
    }
    // For explicitly bounded BIOS/DMA copies containing verified executable
    // code, compile all valid instruction entries ahead of time as well. A
    // computed target without a statically known index can enter these exact
    // ROM-derived fragments and rejoin a larger body. No runtime decoding.
    // Complete bodies stay ahead of fragments in the stable dispatch order.
    for(const auto& copy : config.ram_code) {
        if(!fragment_regions.erase({copy.region.rom_src,copy.region.ram_dst,copy.region.size}))continue;
        anygba::analysis::Image image(rom);image.add_region(copy.region);
        for(unsigned thumb=0;thumb<2;++thumb) {
            const auto width=thumb?2u:4u;
            if(copy.region.ram_dst%width)continue;
            for(auto pc=copy.region.ram_dst;std::uint64_t(pc)+width<=std::uint64_t(copy.region.ram_dst)+copy.region.size;pc+=width) {
                const auto mode=thumb?anygba::analysis::Mode::Thumb:anygba::analysis::Mode::Arm;
                const auto instruction=anygba::analysis::decode_at(image,pc,mode);
                if(!instruction.valid() || std::uint64_t(instruction.next())>std::uint64_t(copy.region.ram_dst)+copy.region.size)continue;
                anygba::analysis::Function fn;fn.entry=pc;fn.mode=mode;fn.insns.emplace(pc,instruction);
                emit_body(fn,image,copy.region);
            }
        }
    }
    shard.close();
    if (!shard) throw std::runtime_error("cannot write native overlays");
    std::cout << '[' << table.str() << "]\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
