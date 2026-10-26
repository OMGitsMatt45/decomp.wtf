// SPDX-License-Identifier: MIT. Compile owner-supplied firmware ahead of time.
// Generated firmware-derived code/data stays in the owner's private project.
#include "analysis/functions.h"
#include "codegen/c_emitter.h"
#include "decode/arm.h"
#include "decode/thumb.h"
#include "anygba/sha256.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>

int main(int argc,char** argv) { try {
    if (argc!=3) throw std::runtime_error("expected BIOS and generated-game directory");
    std::ifstream input(argv[1],std::ios::binary);
    if (!input) throw std::runtime_error("cannot read supplied BIOS");
    const std::vector<std::uint8_t> bytes{std::istreambuf_iterator<char>(input),{}};
    if (bytes.size()!=16384) throw std::runtime_error("BIOS must contain exactly 16384 bytes");
    const std::filesystem::path root(argv[2]);
    std::filesystem::create_directories(root);
    const auto half=[&](unsigned at) {return std::uint16_t(bytes[at]|(unsigned(bytes[at+1])<<8));};
    std::ostringstream declarations,arm,thumb;
    std::ofstream shard;unsigned count=0,arm_count=0,thumb_count=0;
    for (unsigned mode=0;mode<2;++mode) {
        auto& table=mode?thumb:arm;
        for (unsigned at=0;at<bytes.size();at+=mode?2:4) {
            const auto instruction=mode ? anygba::decode::decode_thumb_at(half(at),at+3<bytes.size()?half(at+2):0,at) :
                anygba::decode::decode_arm(std::uint32_t(half(at))|(std::uint32_t(half(at+2))<<16),at);
            if (!instruction.valid()) {table<<"0,\n";continue;}
            if (count%128==0) {
                if (shard.is_open()) {shard.close();if(!shard)throw std::runtime_error("cannot write BIOS source");}
                shard.open(root/("bios_"+std::to_string(count/128)+".c"),std::ios::trunc);
                shard<<"/* Owner firmware-derived native code; keep private. */\n#include <anygba/bios_native.h>\n\n";
            }
            const auto name=std::string("gba_bios_")+(mode?"t_":"a_")+std::to_string(at);
            anygba::analysis::Function fn;fn.entry=at;fn.mode=mode?anygba::analysis::Mode::Thumb:anygba::analysis::Mode::Arm;
            fn.insns.emplace(at,instruction);fn.labels.insert(at);
            anygba::codegen::EmitOptions options;options.name=name;
            auto source=anygba::codegen::emit_function(fn,options);
            const auto guard=source.find("    if (!anygba_ram_variant_valid(");
            if (guard==source.npos) throw std::runtime_error("native firmware entry patch differs from pinned emitter");
            const auto end=source.find('\n',guard);
            source.replace(guard,end-guard,"    anygba_bios_enter(c, "+std::to_string(at)+"u, "+std::to_string(mode)+");");
            shard<<source<<'\n';declarations<<"extern void "<<name<<"(anygba_cpu*);\n";
            table<<name<<",\n";++count;if(mode)++thumb_count;else++arm_count;
        }
    }
    shard.close();if(!shard)throw std::runtime_error("cannot finish BIOS source");
    std::ofstream dispatch(root/"bios_dispatch.c",std::ios::trunc);
    dispatch<<"/* Owner firmware identity, initial data and compiled dispatch. */\n#include <anygba/bios_native.h>\n"
        <<declarations.str()<<"static const uint8_t image[16384]={\n";
    for(unsigned i=0;i<bytes.size();++i)dispatch<<unsigned(bytes[i])<<(i+1==bytes.size()?"":",")<<(i%32==31?"\n":"");
    dispatch<<"};\nstatic const anygba_fn arm[4096]={\n"<<arm.str()<<"};\nstatic const anygba_fn thumb[8192]={\n"<<thumb.str()
        <<"};\nconst anygba_bios anygba_compiled_bios={\""<<anygba::sha256_hex(bytes)<<"\",image,arm,thumb,"
        <<arm_count<<"u,"<<thumb_count<<"u};\n";
    dispatch.close();if(!dispatch)throw std::runtime_error("cannot write BIOS dispatch");
    std::cout<<"{\"arm\":"<<arm_count<<",\"thumb\":"<<thumb_count<<",\"sha256\":\""<<anygba::sha256_hex(bytes)<<"\"}\n";
    return 0;
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;} }
