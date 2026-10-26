// SPDX-License-Identifier: MIT
// Ahead-of-time specialization of complete position-independent ROM routines.
// Runtime selection authenticates their whole image at the current RAM address.
#include "codegen/c_emitter.h"
#include "analysis/cfg.h"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <regex>
#include <set>
#include <sstream>
#include <tuple>

namespace anygba::codegen {
std::string emit_legacy_function(const analysis::Function&,const EmitOptions&);
namespace {
bool movable(const analysis::Function& function) {
    using decode::Op;
    if (function.hit_undefined || !function.has_exit || function.insns.empty() ||
        function.insns.size()>64 || !function.jump_tables.empty()) return false;
    for (const auto& [address,in] : function.insns) {
        if (!in.valid() || in.rn==decode::kPC || (!in.imm && in.rm==decode::kPC) ||
            in.rs==decode::kPC) return false;
        if (in.op==Op::BL || in.op==Op::BL_HI || in.op==Op::BL_LO || in.op==Op::SWI ||
            in.op==Op::MRS || in.op==Op::MSR) return false;
        if (in.op==Op::B && !function.insns.contains(in.imm_value)) return false;
        if (in.op==Op::STM && (!in.reglist || (in.reglist&(1u<<decode::kPC)))) return false;
        if ((in.op==Op::STR || in.op==Op::STRB || in.op==Op::STRH) && in.rd==decode::kPC) return false;
    }
    return true;
}
std::vector<analysis::Function> copied_leaf_sources(const analysis::Image& image) {
    // A source pointer used to copy code is a data pointer: its low bit need
    // not describe the eventual execution mode. Recover complete short leaf
    // bodies at those ROM-backed source pointers, independently of the main
    // function map. This is a finite ROM-derived corpus, compiled at export.
    using decode::Op;
    std::vector<analysis::Function> result;
    std::set<std::pair<std::uint32_t,unsigned>> checked;
    for(std::uint32_t at=0;std::uint64_t(at)+4<=image.rom().size();at+=4) {
        const auto pointer=*image.read32(analysis::kRomBase+at);
        if(!analysis::Image::is_rom(pointer))continue;
        const auto address=analysis::Image::canonical(pointer&~1u);
        for(unsigned thumb=0;thumb<2;++thumb) {
            if((!thumb && pointer&3u) || address%(thumb?2:4) || !checked.emplace(address,thumb).second)continue;
            analysis::Function fn;fn.entry=address;fn.mode=thumb?analysis::Mode::Thumb:analysis::Mode::Arm;
            auto pc=address;
            for(unsigned i=0;i<8;++i) {
                const auto in=analysis::decode_at(image,pc,fn.mode);
                if(!in.valid() || in.cond!=decode::Cond::AL || in.op==Op::B || in.op==Op::BL ||
                    in.op==Op::BL_HI || in.op==Op::BL_LO || in.op==Op::SWI)break;
                fn.insns.emplace(pc,in);
                const bool pc_result=in.rd==decode::kPC && in.op<=Op::MVN &&
                    in.op!=Op::TST && in.op!=Op::TEQ && in.op!=Op::CMP && in.op!=Op::CMN;
                if(in.op==Op::BX || pc_result || (in.op==Op::LDR && in.rd==decode::kPC) ||
                    (in.op==Op::LDM && (in.reglist&(1u<<decode::kPC)))) {
                    fn.has_exit=true;
                    if(movable(fn))result.push_back(std::move(fn));
                    break;
                }
                pc=in.next();
            }
        }
    }
    return result;
}
std::string rebase(const std::string& source,const std::regex& pattern,std::uint32_t origin) {
    std::string result;std::size_t last=0;
    for (auto it=std::sregex_iterator(source.begin(),source.end(),pattern);it!=std::sregex_iterator();++it) {
        const auto& match=*it;const auto address=std::stoul(match[1].str(),nullptr,16);
        result+=source.substr(last,match.position(1)-last);
        result+="(decomp_base+"+std::to_string(std::uint32_t(address)-origin)+"u)";
        last=match.position(1)+match.length(1);
    }
    return result+source.substr(last);
}
}

std::vector<std::filesystem::path> write_relocated(const std::filesystem::path& root,
        const analysis::Image& image,const analysis::Discovery& discovery) {
    struct Row {std::uint32_t prefix,source,size,offset,thumb;std::string name;};
    std::vector<Row> rows;std::ostringstream declarations;
    std::set<std::pair<unsigned,std::vector<std::uint8_t>>> seen;
    std::vector<std::filesystem::path> written;std::ofstream shard;unsigned count=0;
    const auto leaves=copied_leaf_sources(image);
    std::vector<const analysis::Function*> functions;
    for(const auto& [address,function] : discovery.functions)functions.push_back(&function);
    for(const auto& function : leaves)functions.push_back(&function);
    for (const auto* candidate : functions) {
        const auto& function=*candidate;const auto entry=function.entry;
        if (!analysis::Image::is_rom(entry) || !movable(function)) continue;
        const auto range=code_footprint(function,&image);
        const auto size=range.end-range.begin;
        if (size<(function.mode==analysis::Mode::Thumb?2u:4u) || size>512) continue;
        const auto source=image.rom_offset(range.begin,size);if (!source) continue;
        const auto& rom=image.rom();
        const unsigned thumb=function.mode==analysis::Mode::Thumb;
        const std::vector<std::uint8_t> bytes(rom.begin()+*source,rom.begin()+*source+size);
        if (!seen.emplace(thumb,bytes).second) continue;
        if (count%96==0) {
            if (shard.is_open()) {shard.close();if(!shard)throw std::runtime_error("cannot finish relocated code shard");}
            const auto path=root/("relocated_"+std::to_string(count/96)+".c");written.push_back(path);
            shard.open(path,std::ios::trunc);shard<<"/* ROM-derived native routines; keep private. */\n#include <anygba/cpu.h>\n\n";
        }
        const auto name="gba_relocated_"+std::to_string(count++);
        auto labeled=function;
        for(const auto& [pc,in] : function.insns) labeled.labels.insert(pc);
        EmitOptions options;options.name=name+"_body";options.image=&image;
        auto text=emit_legacy_function(labeled,options);
        const auto first=text.find('\n'),guard_end=text.find('\n',first+1);
        if (text.substr(first+1,guard_end-first-1).find("AG_ENTER(c,")==std::string::npos)
            throw std::runtime_error("pinned relocated function guard differs");
        text.erase(first+1,guard_end-first);
        const auto signature="void "+name+"_body(anygba_cpu* c) {\n";
        if (!text.starts_with(signature)) throw std::runtime_error("pinned relocated function signature differs");
        text.replace(0,signature.size(),"static void "+name+"_body(anygba_cpu* c,uint32_t decomp_base,uint32_t decomp_offset) {\n");
        // Only emitted guest-code locations are rebased. Immediate constants in
        // the original instructions retain their exact original meaning.
        text=rebase(text,std::regex(R"(AG_TICK\(c, (0x[0-9a-f]{8}u)\))"),range.begin);
        text=rebase(text,std::regex(R"(c->r\[15\] = (0x[0-9a-f]{8}u);)"),range.begin);
        text=rebase(text,std::regex(R"(AG_ICALL\(c, (0x[0-9a-f]{8}u)\))"),range.begin);
        text=rebase(text,std::regex(R"(if \(\(c->r\[14\] & ~1u\) == (0x[0-9a-f]{8}u)\))"),range.begin);
        text=std::regex_replace(text,std::regex(R"(AG_SPEND\(c, [0-9]+,)"),"AG_SPEND(c, (decomp_base>>24)&15u,");
        std::ostringstream select;
        select<<"    switch(decomp_offset) {\n";
        for(const auto& [pc,in] : function.insns)
            select<<"    case "<<pc-range.begin<<"u: goto L_"<<std::hex<<std::setw(8)<<std::setfill('0')<<pc<<std::dec<<";\n";
        select<<"    default: return;\n    }\n";
        text.insert(text.find('\n')+1,select.str());shard<<text<<'\n';
        for(const auto& [pc,in] : function.insns) {
            // An instruction word provides a cheap lookup key; the selector checks
            // every byte of the complete routine, including bytes before PC.
            const auto offset=pc-range.begin;
            const auto wrapper=name+"_at_"+std::to_string(offset);
            shard<<"void "<<wrapper<<"(anygba_cpu* c) { "<<name<<"_body(c,c->r[15]-"<<offset<<"u,"<<offset<<"u); }\n";
            declarations<<"extern void "<<wrapper<<"(anygba_cpu*);\n";
            rows.push_back({thumb?*image.read16(pc):*image.read32(pc),analysis::kRomBase+*source,size,offset,thumb,wrapper});
        }
    }
    if(shard.is_open()){shard.close();if(!shard)throw std::runtime_error("cannot write relocated code");}
    std::sort(rows.begin(),rows.end(),[](const Row& a,const Row& b){return a.prefix<b.prefix;});
    const auto path=root/"relocated_dispatch.c";written.push_back(path);
    std::ofstream output(path,std::ios::trunc);
    output<<"/* ROM-derived native routine identities; keep private. */\n#include <anygba/relocated.h>\n"<<declarations.str();
    if(rows.empty())output<<"const anygba_relocated_entry* const anygba_relocated_entries=0;\n";
    else {
        output<<"static const anygba_relocated_entry entries[]={\n";
        for(const auto& row : rows) output<<"{"<<row.prefix<<"u,"<<row.source<<"u,"<<row.size<<"u,"<<row.offset<<"u,"<<row.thumb<<"u,"<<row.name<<"},\n";
        output<<"};\nconst anygba_relocated_entry* const anygba_relocated_entries=entries;\n";
    }
    output<<"const uint32_t anygba_relocated_count="<<rows.size()<<"u;\n";
    output.close();if(!output)throw std::runtime_error("cannot write relocated dispatch");
    return written;
}
}
