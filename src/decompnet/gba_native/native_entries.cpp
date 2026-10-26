// SPDX-License-Identifier: MIT. Share compiled bodies with secondary entry points.
#include "codegen/c_emitter.h"
#include <algorithm>
#include <fstream>
#include <cstdio>
#include <iomanip>
#include <iterator>
#include <sstream>
#include <stdexcept>

namespace anygba::codegen {
std::string emit_legacy_function(const analysis::Function&,const EmitOptions&);
std::vector<std::filesystem::path> write_legacy_project(const std::filesystem::path&,const analysis::Image&,
    const analysis::Discovery&,const ProjectInfo&);
std::vector<std::filesystem::path> write_relocated(const std::filesystem::path&,const analysis::Image&,
    const analysis::Discovery&);

static void bound_source_units(const std::filesystem::path& root,const analysis::Image& image,
        const analysis::Discovery& discovery,const ProjectInfo& info,std::vector<std::filesystem::path>& written) {
    // A fixed function count can still produce a very large C translation
    // unit. Keep complete native bodies together and budget by emitted bytes.
    std::set<std::filesystem::path> previous,current;
    for(const auto& path : written)
        if(path.filename().string().starts_with("funcs_") && path.extension()==".c")previous.insert(path);
    std::ofstream output;std::size_t bytes=0;unsigned index=0;
    const auto next=[&]() {
        if(output.is_open()){output.close();if(!output)throw std::runtime_error("cannot finish native C unit");}
        char name[64];std::snprintf(name,sizeof name,"funcs_%03u.c",index++);
        const auto path=root/name;current.insert(path);output.open(path,std::ios::binary|std::ios::trunc);
        if(!output)throw std::runtime_error("cannot create native C unit");
        output<<"/* Generated native game code. Keep ROM-derived source private. */\n#include \"game.h\"\n\n";bytes=0;
    };
    const auto write_source=[&](const std::string& source) {
        if(!output.is_open() || (bytes && bytes+source.size()>1024*1024))next();
        output<<source<<'\n';bytes+=source.size()+1;
    };
    EmitOptions options;options.image=&image;options.functions=&discovery.functions;
    for(const auto& [address,function] : discovery.functions) {
        const auto replacement=info.replacements.find(address);
        if(replacement==info.replacements.end() && function.insns.size()>2048) {
            // All architectural state is in anygba_cpu. Split large CFGs only
            // between complete instructions; exits rejoin native dispatch.
            // This also bounds compiler memory for large individual functions.
            std::ostringstream declarations,resume;std::string entry_part;
            const auto name=function_name(address);
            const auto pc=analysis::Image::is_rom(address)?"0x08000000u+(c->r[15]&0x01ffffffu)":"c->r[15]";
            resume<<"void "<<name<<"_resume(anygba_cpu* c) { const uint32_t pc="<<pc<<";\n";
            auto cursor=function.insns.begin();unsigned piece=0;
            while(cursor!=function.insns.end()) {
                analysis::Function part;part.mode=function.mode;part.source=function.source;part.entry=cursor->first;
                for(unsigned n=0;n<512 && cursor!=function.insns.end();++n,++cursor)part.insns.insert(*cursor);
                const auto part_name=name+"_part_"+std::to_string(piece++);
                EmitOptions part_options=options;part_options.name=part_name;
                write_source(emit_function(part,part_options));
                declarations<<"extern void "<<part_name<<"_resume(anygba_cpu*);\n";
                resume<<"    if(pc>="<<part.insns.begin()->first<<"u && pc<="<<part.insns.rbegin()->first<<"u) { "
                      <<part_name<<"_resume(c); return; }\n";
                if(part.insns.contains(function.entry))entry_part=part_name;
            }
            if(entry_part.empty())throw std::runtime_error("native CFG does not contain its entry");
            resume<<"}\nvoid "<<name<<"(anygba_cpu* c) { c->r[15]="<<function.entry<<"u; "<<entry_part<<"_resume(c); }\n";
            write_source(declarations.str()+resume.str());continue;
        }
        const auto source=replacement==info.replacements.end()?emit_function(function,options):
            "void "+function_name(address)+"(anygba_cpu* c) { "+replacement->second+"(c); }\n";
        write_source(source);
    }
    if(output.is_open()){output.close();if(!output)throw std::runtime_error("cannot write native C unit");}
    for(const auto& path : previous)if(!current.contains(path))std::filesystem::remove(path);
    written.erase(std::remove_if(written.begin(),written.end(),[&](const auto& path){return previous.contains(path);}),written.end());
    written.insert(written.end(),current.begin(),current.end());
}

std::string emit_function(const analysis::Function& function,const EmitOptions& options) {
    if (function.insns.size()<2) return emit_legacy_function(function,options);
    auto labeled=function;
    for (const auto& [address,instruction] : labeled.insns) labeled.labels.insert(address);
    auto source=emit_legacy_function(labeled,options);
    const auto name=options.name.empty()?function_name(function.entry):options.name;
    const auto prefix="void "+name+"(anygba_cpu* c) {\n";
    if (!source.starts_with(prefix)) throw std::runtime_error("pinned native function prefix differs");
    // The first generated statement is the ROM-patch or complete RAM-byte guard.
    // Keep that guard ahead of the entry switch, including on resumed entries.
    auto after_guard=source.find('\n',prefix.size());
    auto guard=source.substr(prefix.size(),after_guard-prefix.size());
    if (analysis::Image::is_rom(function.entry)) guard="    AG_ENTER(c, decomp_entry);";
    else {
        const auto pc=guard.find("c->r[15]="),end=guard.find(';',pc);
        if (pc==guard.npos || end==guard.npos) throw std::runtime_error("pinned RAM entry guard differs");
        guard.replace(pc,end-pc,"c->r[15]=decomp_entry");
    }
    source.replace(prefix.size(),after_guard-prefix.size(),guard);
    after_guard=prefix.size()+guard.size();
    std::ostringstream select;
    select<<"    switch (decomp_entry) {\n";
    for (const auto& [address,instruction] : function.insns) {
        char label[32];std::snprintf(label,sizeof label,"L_%08x",address);
        select<<"    case "<<address<<"u: goto "<<label<<";\n";
    }
    select<<"    default: c->r[15]=decomp_entry; return;\n    }\n";
    source.insert(after_guard+1,select.str());
    source.replace(0,prefix.size(),"static void "+name+"_body(anygba_cpu* c,uint32_t decomp_entry) {\n");
    source+="\nvoid "+name+"(anygba_cpu* c) { "+name+"_body(c,"+std::to_string(function.entry)+"u); }\n";
    const auto entry=analysis::Image::is_rom(function.entry)?"0x08000000u+(c->r[15]&0x01ffffffu)":"c->r[15]";
    source+="void "+name+"_resume(anygba_cpu* c) { "+name+"_body(c,"+entry+"); }\n";
    return source;
}

std::vector<std::filesystem::path> write_project(const std::filesystem::path& root,const analysis::Image& image,
        const analysis::Discovery& discovery,const ProjectInfo& info) {
    auto written=write_legacy_project(root,image,discovery,info);
    bound_source_units(root,image,discovery,info,written);
    const auto relocated=write_relocated(root,image,discovery);
    written.insert(written.end(),relocated.begin(),relocated.end());
    const auto& functions=discovery.functions;
    std::map<std::pair<std::uint32_t,unsigned>,std::uint32_t> owners;
    for (const auto& [address,function] : functions) owners[{address,function.mode==analysis::Mode::Thumb}]=address;
    for (const auto& [address,function] : functions) {
        if (info.replacements.contains(address)) continue;
        for (const auto& [pc,instruction] : function.insns)
            owners.try_emplace({pc,function.mode==analysis::Mode::Thumb},address);
    }
    std::ostringstream rows,prototypes;
    struct Footprint {analysis::AddressRange range;std::uint32_t source;};
    std::map<std::uint32_t,Footprint> footprints;
    for (const auto& [address,function] : functions) {
        auto range=info.replacements.contains(address)?analysis::AddressRange{}:code_footprint(function,&image);
        std::uint32_t source=0;
        if (!analysis::Image::is_rom(address) && range.end>range.begin)
            if (const auto offset=image.rom_offset(range.begin,range.end-range.begin)) source=analysis::kRomBase+*offset;
        footprints.emplace(address,Footprint{range,source});
        if (function.insns.size()>1 && !info.replacements.contains(address))
            prototypes<<"extern void "<<function_name(address)<<"_resume(anygba_cpu*);\n";
    }
    for (const auto& [key,owner] : owners) {
        const auto& [address,thumb]=key;const auto& footprint=footprints.at(owner);
        const auto name=function_name(owner)+(address==owner?"":"_resume");
        rows<<"    {0x"<<std::hex<<std::setfill('0')<<std::setw(8)<<address<<"u, "<<std::dec<<thumb<<", "<<name
            <<", 0x"<<std::hex<<std::setw(8)<<footprint.range.begin<<"u, 0x"<<std::setw(8)<<footprint.range.end
            <<"u, 0x"<<std::setw(8)<<footprint.source<<"u},\n";
    }
    const auto path=root/"dispatch.c";
    std::ifstream input(path,std::ios::binary);
    std::string text{std::istreambuf_iterator<char>(input),{}};
    const std::string marker="static const anygba_function_entry functions[] = {\n";
    const auto begin=text.find(marker),end=text.find("};\n",begin);
    if (begin==text.npos || end==text.npos) throw std::runtime_error("pinned native dispatch table differs");
    text.replace(begin+marker.size(),end-begin-marker.size(),rows.str());
    const auto count="    functions,\n    "+std::to_string(functions.size())+"u,\n";
    const auto position=text.find(count);
    if (position==text.npos) throw std::runtime_error("pinned native dispatch count differs");
    text.replace(position,count.size(),"    functions,\n    "+std::to_string(owners.size())+"u,\n");
    text.insert(begin,prototypes.str());
    std::ofstream output(path,std::ios::binary|std::ios::trunc);output<<text;output.close();
    if (!output) throw std::runtime_error("cannot write native secondary entries");
    return written;
}
}
