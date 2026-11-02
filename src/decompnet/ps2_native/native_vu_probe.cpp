// SPDX-License-Identifier: CC0-1.0
// Run an original vector program through the actual memory/GS/pipeline interfaces.
#include "runtime/ps2_vu1.h"
#include "runtime/ps2_memory.h"
#include "runtime/gs/gs_frontend.h"
#include "decomp_vu_execution.hpp"
#include <cstring>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

int main(int argc,char **argv) {
    if(argc!=7&&argc!=8)return 2;
    const unsigned unit=unsigned(std::stoul(argv[1])),seed=unsigned(std::stoul(argv[2]));
    const unsigned budget=unsigned(std::stoul(argv[3]));
    const unsigned iterations=argc==8?unsigned(std::stoul(argv[7])):1u;
    if(!iterations||iterations>1000000u)return 2;
    std::ifstream input(argv[4],std::ios::binary);
    std::vector<uint8_t> original((std::istreambuf_iterator<char>(input)),{});
    if(original.empty()||original.size()>4096||original.size()%8||!budget)return 3;
    PS2Memory memory;if(!memory.initialize())return 4;
    GS gs;gs.init(memory.getGSVRAM(),static_cast<uint32_t>(PS2_GS_VRAM_SIZE),&memory.gs());
    uint8_t *code=unit?memory.getVU1Code():memory.getVU0Code();
    uint8_t *data=unit?memory.getVU1Data():memory.getVU0Data();
    const uint32_t codeSize=unit?PS2_VU1_CODE_SIZE:PS2_VU0_CODE_SIZE;
    const uint32_t dataSize=unit?PS2_VU1_DATA_SIZE:PS2_VU0_DATA_SIZE;
    std::memcpy(code,original.data(),original.size());
    const bool negative=std::string(argv[6])=="changed";
    if(negative){const uint64_t unknown=~uint64_t(0);std::memcpy(code,&unknown,8);}
    VU1Interpreter vu(unit?VU1Interpreter::Unit::VU1:VU1Interpreter::Unit::VU0);
    constexpr uint32_t values[]={0x3f800000,0xc0000000,0x00800001,0x80000000,
        0x7f7fffff,0x00000001,0x7fc00001,0xff800000};
    for(unsigned reg=0;reg<32;++reg)for(unsigned lane=0;lane<4;++lane){
        const uint32_t value=values[(reg+lane+seed)%8];std::memcpy(&vu.state().vf[reg][lane],&value,4);
    }
    for(unsigned lane=0;lane<4;++lane){
        const uint32_t value=values[(lane+seed)%8];std::memcpy(&vu.state().acc[lane],&value,4);
    }
    for(unsigned at=0;at<dataSize;at+=4){
        const uint32_t value=values[(at/4+seed)%8];std::memcpy(data+at,&value,4);
    }
    const auto started=std::chrono::steady_clock::now();
    for(unsigned iteration=0;iteration<iterations;++iteration){
        vu.execute(code,codeSize,data,dataSize,gs,&memory,0,0,0,budget);
        unsigned resumes=0;
        while(!negative&&vu.state().pc<original.size()&&resumes++<256) {
            const uint32_t previousPc=vu.state().pc;const uint64_t previousCycles=vu.state().cycles;
            vu.resume(code,codeSize,data,dataSize,gs,&memory,0,0,budget);
            if(vu.state().pc==previousPc&&vu.state().cycles==previousCycles)break;
        }
        if(resumes>=256)return 5;
    }
    if(iterations>1)std::fprintf(stderr,"{\"iterations\":%u,\"elapsed_ns\":%llu,\"native_pairs\":%llu}\n",iterations,
        static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count()),
        static_cast<unsigned long long>(decomp_ps2::execution::vu_native_pairs.load()));
#ifdef DECOMP_PS2_NATIVE_VU
    if(vu.interpretedPairsExecuted()||decomp_ps2::execution::vu_interpreted_pairs.load())return 6;
    if(negative){
        if(!decomp_ps2::execution::vu_coverage_misses.load()||vu.compiledPairsExecuted()||vu.state().cycles)return 7;
    }else if(!vu.compiledPairsExecuted()||decomp_ps2::execution::vu_coverage_misses.load())return 8;
#endif
    std::ofstream output(argv[5],std::ios::binary);
    output.write(reinterpret_cast<const char*>(&vu.state()),sizeof(VU1State));
    output.write(reinterpret_cast<const char*>(data),dataSize);
    return output?0:9;
}
