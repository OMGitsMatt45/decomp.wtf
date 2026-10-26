// SPDX-License-Identifier: MIT
// Original inference of guarded ROM-to-RAM code views from decoded call sites.
#include "analysis/functions.h"
#include "analysis/cfg.h"
#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <set>
#include <tuple>

namespace {
using namespace anygba;
using Value = std::optional<std::uint32_t>;
bool ram(std::uint32_t address) {
    return (address >= 0x02000000 && address < 0x02040000) ||
           (address >= 0x03000000 && address < 0x03008000);
}
Value shifted(Value value, decode::Shift shift, unsigned amount) {
    if (!value) return {};
    switch (shift) {
    case decode::Shift::LSL: return amount >= 32 ? 0 : *value << amount;
    case decode::Shift::LSR: return amount >= 32 ? 0 : *value >> amount;
    case decode::Shift::ASR: return std::uint32_t(std::int32_t(*value) >> (amount >= 32 ? 31 : amount));
    default: return {};
    }
}
}

int main(int argc, char** argv) { try {
    if (argc != 2) throw std::runtime_error("expected an original ROM");
    std::ifstream input(argv[1], std::ios::binary);
    if (!input) throw std::runtime_error("cannot read ROM for copy analysis");
    const std::vector<std::uint8_t> bytes{std::istreambuf_iterator<char>(input), {}};
    analysis::Image image(bytes);
    analysis::DiscoveryOptions options;
    options.entries.push_back({analysis::kRomBase, analysis::Mode::Arm, analysis::EntrySource::RomEntry});
    const auto discovery = analysis::discover(image, options);
    std::set<std::pair<std::uint32_t,unsigned>> decoded_code;
    for (const auto& [entry,function] : discovery.functions) {
        if (function.hit_undefined) continue;
        for (const auto& [address,instruction] : function.insns)
            decoded_code.emplace(address,function.mode == analysis::Mode::Thumb);
    }
    std::set<std::tuple<std::uint32_t,std::uint32_t,std::uint32_t,unsigned>> copies;
    std::set<std::tuple<std::uint32_t,std::uint32_t,std::uint32_t,unsigned>> instruction_copies;
    std::set<std::pair<std::uint32_t,unsigned>> entries;
    for (std::size_t offset = 0; offset + 4 <= bytes.size(); offset += 4) {
        const auto value = *image.read32(analysis::kRomBase + std::uint32_t(offset));
        const unsigned thumb = value & 1u;
        if (ram(value & ~1u) && (thumb || !(value & 3u))) entries.emplace(value & ~1u, thumb);
    }
    const auto candidate = [&](Value source, Value destination, Value control, unsigned multiplier, bool masked,
                               bool inline_copy=false,bool instruction_copy=false) {
        if (!source || !destination || !control || !analysis::Image::is_rom(*source) || !ram(*destination)) return;
        const std::uint32_t count = masked ? *control & 0x1fffffu : *control;
        const auto size = std::uint64_t(count) * multiplier;
        const auto from = analysis::Image::canonical(*source);
        const auto end = *destination < 0x03000000 ? 0x02040000u : 0x03008000u;
        if (!size || size > end - *destination || !image.contains(from, std::uint32_t(size))) return;
        for (unsigned thumb = 0; thumb < 2; ++thumb) {
            const unsigned alignment = thumb ? 2 : 4;
            if (from % alignment || *destination % alignment || size % alignment) continue;
            const auto first=analysis::decode_at(image,from,thumb?analysis::Mode::Thumb:analysis::Mode::Arm);
            // IRQ and sound routines can be naked assembly, including an
            // instruction-set switch near their first instruction. A standard
            // stack prologue or prior ROM CFG is not evidence they require.
            // The independent RAM walk and complete-body guard validate the
            // hypothesis before it can ever select generated code.
            if (!first.valid() || first.cond==decode::Cond::NV) continue;
            if(inline_copy && !decoded_code.contains({from,thumb}))continue;
            if (copies.size() >= 4096) throw std::runtime_error("too many bounded ROM-to-RAM copy hypotheses");
            copies.emplace(from,*destination,std::uint32_t(size),thumb);
            if(instruction_copy)instruction_copies.emplace(from,*destination,std::uint32_t(size),thumb);
        }
    };
    for (const auto& [entry, function] : discovery.functions) {
        std::array<Value,16> registers{};
        std::uint32_t previous = 0;
        Value copy_source;
        std::uint32_t copy_registers=0;
        unsigned copy_width=0;
        std::array<Value,4> dma_source{},dma_destination{},dma_count{};
        for (const auto& [address, instruction] : function.insns) {
            using decode::Op;
            if (previous != address) {
                registers={};copy_source={};dma_source={};dma_destination={};dma_count={};
            }
            const auto reg = [&](unsigned index) -> Value {
                if (index == decode::kPC) return instruction.pc_align ? instruction.pc_value() & ~3u : instruction.pc_value();
                return registers[index];
            };
            const auto operand = [&]() -> Value {
                if (instruction.imm) return instruction.imm_value;
                if (instruction.shift_by_reg) return {};
                return shifted(reg(instruction.rm),instruction.shift,instruction.shift_amount);
            };
            const bool call = instruction.op == Op::BL || instruction.op == Op::BL_LO;
            const bool service = instruction.op == Op::SWI;
            if (instruction.cond==decode::Cond::AL && (instruction.op==Op::STR || instruction.op==Op::STRH)) {
                const auto base=reg(instruction.rn),offset=operand(),value=reg(instruction.rd);
                if (base && offset && value) {
                    const auto at=instruction.pre?(instruction.up?*base+*offset:*base-*offset):*base;
                    if (at>=0x040000b0 && at<0x040000e0) {
                        const unsigned channel=(at-0x040000b0)/12,part=(at-0x040000b0)%12;
                        if (instruction.op==Op::STR && part==0) dma_source[channel]=value;
                        else if (instruction.op==Op::STR && part==4) dma_destination[channel]=value;
                        else if (part==8) dma_count[channel]=*value&0xffffu;
                        const bool enabled=(instruction.op==Op::STR && part==8 && (*value&0x80000000u)) ||
                            (instruction.op==Op::STRH && part==10 && (*value&0x8000u));
                        if (enabled && dma_count[channel]) {
                            const auto control=instruction.op==Op::STR?*value>>16:*value;
                            if (((control>>7)&3u)!=2u) {
                                const auto count=*dma_count[channel]?*dma_count[channel]:(channel==3?65536u:16384u);
                                candidate(dma_source[channel],dma_destination[channel],count,(control&0x400u)?4:2,false,false,true);
                            }
                        }
                    }
                }
            }
            // Common inline copy loops do not call memcpy or a BIOS service.
            // Their first fall-through iteration supplies a ROM source and RAM
            // destination. The generated body's complete byte guard remains the
            // authority; the view need not assume the loop's eventual length.
            if (instruction.cond==decode::Cond::AL && copy_source) {
                Value destination;
                if (instruction.op==Op::STM && copy_width==0 && instruction.reglist==copy_registers && instruction.up)
                    destination=reg(instruction.rn);
                else if (((instruction.op==Op::STR && copy_width==4) ||
                          (instruction.op==Op::STRB && copy_width==1) ||
                          (instruction.op==Op::STRH && copy_width==2)) && instruction.rd==copy_registers) {
                    const auto base=reg(instruction.rn),offset=operand();
                    if (base && offset) destination=instruction.pre?(instruction.up?*base+*offset:*base-*offset):*base;
                }
                if (destination && ram(*destination)) {
                    const auto end=*destination<0x03000000?0x02040000u:0x03008000u;
                    const auto room=std::min<std::uint32_t>(end-*destination,
                        analysis::kRomBase+std::uint32_t(bytes.size())-analysis::Image::canonical(*copy_source));
                    candidate(copy_source,destination,room&~3u,1,false,true);
                }
            }
            copy_source={};
            if (instruction.cond==decode::Cond::AL && instruction.op==Op::LDM && instruction.up) {
                const auto base=reg(instruction.rn);
                if (base && analysis::Image::is_rom(*base)) {
                    copy_source=instruction.pre?*base+4u:*base;
                    copy_registers=instruction.reglist;copy_width=0;
                }
            } else if (instruction.cond==decode::Cond::AL &&
                       (instruction.op==Op::LDR || instruction.op==Op::LDRB || instruction.op==Op::LDRH)) {
                const auto base=reg(instruction.rn),offset=operand();
                if (base && offset) {
                    const auto at=instruction.pre?(instruction.up?*base+*offset:*base-*offset):*base;
                    if (analysis::Image::is_rom(at) && image.contains(at,4)) {
                        copy_source=at;copy_registers=instruction.rd;
                        copy_width=instruction.op==Op::LDR?4:instruction.op==Op::LDRB?1:2;
                    }
                }
            }
            if (instruction.cond == decode::Cond::AL && (call || service)) {
                std::optional<unsigned> bios_service;
                const auto service_number=[](const decode::Insn& op) {
                    return op.thumb?op.imm_value&255u:(op.imm_value>>16)&255u;
                };
                if(service)bios_service=service_number(instruction);
                if(call && instruction.op==Op::BL && analysis::Image::is_rom(instruction.imm_value)) {
                    auto callee=analysis::decode_at(image,instruction.imm_value,function.mode);
                    if(callee.op==Op::B && callee.cond==decode::Cond::AL)
                        callee=analysis::decode_at(image,callee.imm_value,function.mode);
                    if(callee.op==Op::SWI && callee.cond==decode::Cond::AL)bios_service=service_number(callee);
                }
                // ABI call hypotheses are harmless unless the complete decoded
                // routine's bytes actually appear at the RAM destination.
                // Preserve independent sizes/modes instead of merging overlaps.
                if (call) {
                    candidate(reg(1),reg(0),reg(2),1,false); // memcpy convention
                    candidate(reg(0),reg(1),reg(2),1,false);
                    candidate(reg(0),reg(1),reg(2),2,true);
                    candidate(reg(0),reg(1),reg(2),4,true);
                }
                if(bios_service) {
                    const unsigned number=*bios_service;
                    if (number == 0x0b || number == 0x0c) {
                        // CpuSet / CpuFastSet: fixed-source fill is data, not
                        // a copied executable image. CpuFastSet rounds to 8 words.
                        if (reg(2) && !(*reg(2) & (1u << 24))) {
                            auto control = reg(2);
                            if (number == 0x0c) control = ((*control & 0x1fffffu) + 7u) & ~7u;
                            candidate(reg(0),reg(1),control,number == 0x0c || (*reg(2) & (1u << 26)) ? 4 : 2,true,false,true);
                        }
                    }
                }
                for (unsigned index : {0u,1u,2u,3u,12u,14u}) registers[index] = {};
            } else if (instruction.op <= Op::MVN && instruction.op != Op::TST && instruction.op != Op::TEQ &&
                       instruction.op != Op::CMP && instruction.op != Op::CMN) {
                Value value;
                const auto left=reg(instruction.rn),right=operand();
                if (instruction.cond == decode::Cond::AL) {
                    if (instruction.op == Op::MOV) value=right;
                    else if (instruction.op == Op::MVN && right) value=~*right;
                    else if (left && right) switch (instruction.op) {
                    case Op::ADD:value=*left+*right;break;
                    case Op::SUB:value=*left-*right;break;
                    case Op::RSB:value=*right-*left;break;
                    case Op::AND:value=*left & *right;break;
                    case Op::ORR:value=*left | *right;break;
                    case Op::BIC:value=*left & ~*right;break;
                    default:break;
                    }
                }
                registers[instruction.rd]=value;
            } else if (instruction.op == Op::LDR || instruction.op == Op::LDRB || instruction.op == Op::LDRH ||
                       instruction.op == Op::LDRSB || instruction.op == Op::LDRSH) {
                Value value;const auto base=reg(instruction.rn),offset=operand();
                if (instruction.cond == decode::Cond::AL && base && offset && instruction.op == Op::LDR) {
                    const auto at=instruction.pre ? (instruction.up ? *base+*offset : *base-*offset) : *base;
                    if (!(at&3u) && analysis::Image::is_rom(at)) value=image.read32(at);
                }
                registers[instruction.rd]=value;
                if (instruction.writeback) registers[instruction.rn]={};
            } else if (instruction.op == Op::LDM) {
                for (unsigned index=0;index<16;++index) if (instruction.reglist & (1u<<index)) registers[index]={};
                if (instruction.writeback) registers[instruction.rn]={};
            } else if ((instruction.op == Op::STR || instruction.op == Op::STRB || instruction.op == Op::STRH ||
                        instruction.op == Op::STM) && instruction.writeback) registers[instruction.rn]={};
            else if (instruction.op == Op::MRS || instruction.op == Op::MUL || instruction.op == Op::MLA ||
                     instruction.op == Op::SWP || instruction.op == Op::SWPB) registers[instruction.rd]={};
            else if (instruction.op == Op::UMULL || instruction.op == Op::UMLAL ||
                     instruction.op == Op::SMULL || instruction.op == Op::SMLAL) {
                registers[instruction.rd]={};registers[instruction.rn]={};
            }
            previous=instruction.next();
            // A conditional branch has a first fall-through edge. Keep values
            // in registers that its loop body did not write, including DMA
            // parameters prepared before a small initialization loop.
            if ((instruction.op==Op::B && instruction.cond==decode::Cond::AL) || instruction.op==Op::BX ||
                (instruction.op!=Op::B && instruction.rd==decode::kPC)) registers={};
        }
    }
    // Analyze copies at their execution addresses. Their literal pools and
    // veneers can reveal ROM callees that are not discoverable at storage VMA.
    std::set<std::pair<std::uint32_t,unsigned>> rom_entries;
    for (const auto& [from,to,size,thumb] : copies) {
        analysis::Image view(bytes);view.add_region({from,to,size});
        std::vector<std::pair<std::uint32_t,unsigned>> pending{{to,thumb}};
        for (const auto& entry : entries)
            if (entry.second==thumb && to<=entry.first && std::uint64_t(entry.first)+2<=std::uint64_t(to)+size &&
                decoded_code.contains({from+entry.first-to,thumb})) pending.push_back(entry);
        std::set<std::pair<std::uint32_t,unsigned>> walked;
        const auto found=[&](std::uint32_t address,unsigned mode) {
            if (analysis::Image::is_rom(address) && image.contains(address,mode?2:4))
                rom_entries.emplace(analysis::Image::canonical(address),mode);
            else if (to<=address && std::uint64_t(address)+(mode?2:4)<=std::uint64_t(to)+size)
                pending.emplace_back(address,mode);
        };
        while (!pending.empty()) {
            const auto [address,mode]=pending.back();pending.pop_back();
            if (!walked.emplace(address,mode).second) continue;
            if (walked.size()>65536) throw std::runtime_error("RAM call graph exceeds analysis limit");
            const auto walk=analysis::walk_function(view,{address,mode?analysis::Mode::Thumb:analysis::Mode::Arm,
                analysis::EntrySource::Config},{},{},{{0x08000000,0x0e000000}});
            for (const auto& target : walk.found) found(target.addr,target.mode==analysis::Mode::Thumb);
            for (const auto label : walk.function.labels)
                if (analysis::Image::is_rom(label)) found(label,mode);
        }
    }
    std::cout << "{\"copies\":[";
    unsigned index=0;
    for (const auto& [from,to,size,thumb] : copies) {
        std::cout << (index++ ? "," : "") << "{\"rom\":" << from << ",\"address\":" << to
                  << ",\"size\":" << size << ",\"mode\":\"" << (thumb ? "thumb" : "arm")
                  << "\",\"instruction_fragments\":"<<(instruction_copies.contains({from,to,size,thumb})?"true":"false")<<"}";
    }
    std::cout << "],\"entries\":[";index=0;
    for (const auto& [address,thumb] : entries) {
        bool backed=false;
        for (const auto& [from,to,size,mode] : copies)
            if (thumb==mode && to<=address && std::uint64_t(address)+(thumb?2:4)<=std::uint64_t(to)+size &&
                decoded_code.contains({from+address-to,thumb})) {backed=true;break;}
        if (backed) std::cout << (index++ ? "," : "") << "{\"address\":" << address << ",\"mode\":\"" << (thumb?"thumb":"arm") << "\"}";
    }
    std::cout << "],\"rom_entries\":[";index=0;
    for (const auto& [address,thumb] : rom_entries)
        std::cout<<(index++?",":"")<<"{\"address\":"<<address<<",\"mode\":\""<<(thumb?"thumb":"arm")<<"\"}";
    std::cout << "]}\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; } }
