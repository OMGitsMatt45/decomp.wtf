// SPDX-License-Identifier: MIT
// Bounded ARM11 execution harness. This is not a 3DS kernel or graphics runtime.
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "hash.hpp"
extern "C" {
#include "recomp.h"
extern const Entry recomp_entries[];
extern const uint32_t recomp_entry_count;
}
#include "layout.hpp"

struct Memory {
    std::vector<uint8_t*> reads{std::vector<uint8_t*>(1u << 20)};
    std::vector<uint8_t*> writes{std::vector<uint8_t*>(1u << 20)};
    std::vector<std::vector<uint8_t>> regions;
    void map(uint32_t at, size_t size, bool writable, const std::vector<uint8_t>& bytes={}) {
        if (!size) return;
        size=(size+4095)&~size_t(4095);
        if ((at&4095) || size>0x10000000u || uint64_t(at)+size>0x10000000u || bytes.size()>size)
            throw std::runtime_error("invalid guest mapping");
        for(size_t i=0;i<size;i+=4096) if(reads[(at+i)>>12]) throw std::runtime_error("overlapping guest mapping");
        regions.emplace_back(size);
        auto& region=regions.back();
        std::copy(bytes.begin(),bytes.end(),region.begin());
        for(size_t i=0;i<size;i+=4096) {
            reads[(at+i)>>12]=region.data()+i;
            if(writable)writes[(at+i)>>12]=region.data()+i;
        }
    }
};
static uint8_t read8(Context* c,uint32_t at) {
    auto* memory=static_cast<Memory*>(c->user);
    if(!memory->reads[at>>12]) throw std::runtime_error("read from unmapped 3DS memory");
    return memory->reads[at>>12][at&4095];
}
static uint16_t read16(Context* c,uint32_t at) { return uint16_t(read8(c,at))|uint16_t(read8(c,at+1))<<8; }
static uint32_t read32(Context* c,uint32_t at) { return uint32_t(read16(c,at))|uint32_t(read16(c,at+2))<<16; }
static void write8(Context* c,uint32_t at,uint8_t value) {
    auto* memory=static_cast<Memory*>(c->user);
    if(!memory->writes[at>>12]) throw std::runtime_error("write to unmapped or read-only 3DS memory");
    memory->writes[at>>12][at&4095]=value;
}
static void write16(Context* c,uint32_t at,uint16_t value) { write8(c,at,uint8_t(value));write8(c,at+1,uint8_t(value>>8)); }
static void write32(Context* c,uint32_t at,uint32_t value) { write16(c,at,uint16_t(value));write16(c,at+2,uint16_t(value>>16)); }
static void unsupported(Context*,uint32_t,uint32_t) { throw std::runtime_error("unsupported ARM11 instruction: interpreter fallback is disabled"); }
static Code lookup(Context*,uint32_t address) {
    auto* end=recomp_entries+recomp_entry_count;
    auto* entry=std::lower_bound(recomp_entries,end,address,[](const Entry& e,uint32_t at){return e.address<at;});
    return entry!=end && entry->address==address ? entry->code : nullptr;
}

int main(int argc,char** argv) {
    try {
        if(argc<2 || argc>3) throw std::runtime_error("usage: ctr_probe ASSET_DIRECTORY [INSTRUCTION_BUDGET]");
        int budget=argc==3?std::stoi(argv[2]):100000;
        if(budget<1 || budget>10000000) throw std::runtime_error("instruction budget must be 1 through 10000000");
        Memory memory;
        for(const auto& segment:segments) {
            std::vector<uint8_t> bytes;
            if(segment.size) {
                auto path=std::filesystem::path(argv[1])/segment.file;
                if(std::filesystem::file_size(path)!=segment.size || input_sha256(path)!=segment.sha256)
                    throw std::runtime_error("3DS segment identity differs; preserve edits and re-export original assets");
                std::ifstream file(path,std::ios::binary);
                bytes.assign(std::istreambuf_iterator<char>(file),{});
                if(bytes.size()!=segment.size) throw std::runtime_error("3DS segment was truncated");
            }
            memory.map(segment.address,segment.allocated,segment.writable,bytes);
        }
        memory.map(0x0fff0000u,0x10000u,true);
        const Host host={read8,read16,read32,write8,write16,write32,unsupported,lookup};
        uint32_t vfp[32]={},fpscr=0;
        Context context={};
        context.r[15]=entry_point;context.r[13]=0x10000000u;
        context.budget=budget;context.host=&host;context.user=&memory;
        context.read_pages=memory.reads.data();context.write_pages=memory.writes.data();
        context.vfp=vfp;context.fpscr=&fpscr;
        bool exited=false;
        while(context.budget>0) {
            auto function=lookup(&context,context.r[15]|context.thumb);
            if(!function) throw std::runtime_error("untranslated ARM11 target; no fallback was run");
            auto before=context.budget;
            context.exit=EXIT_NONE;
            function(&context);
            if(context.exit==EXIT_SVC) {
                if(context.svc==3) {exited=true;break;} // svcExitProcess
                throw std::runtime_error("unimplemented 3DS kernel service");
            }
            if(context.exit==EXIT_BUDGET) break;
            if(context.budget>=before) throw std::runtime_error("translated code made no progress");
        }
        std::cout<<"{\"schema\":\"decomp.wtf.3ds-cpu-probe/v1\",\"process_exited\":"<<(exited?"true":"false")
            <<",\"r0\":"<<context.r[0]<<",\"r1\":"<<context.r[1]<<",\"native_instructions\":"<<(budget-context.budget)
            <<",\"interpreted_instructions\":0,\"graphics\":false,\"retail_qualified\":false}\n";
        return exited?0:2;
    } catch(const std::exception& error) {std::cerr<<"3DS probe: "<<error.what()<<'\n';return 1;}
}
