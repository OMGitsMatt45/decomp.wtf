// SPDX-License-Identifier: MIT
#pragma once
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace decomp_ps2 {
// Optional integration-test input, held in guest-vsync ticks.
class CommandPad {
    uint64_t sequence_=0,until_=0;
    uint32_t mask_=0,edge_=0;
    std::chrono::steady_clock::time_point next_{};
public:
    void accept(const std::string &line,uint64_t tick){
        if(line.empty())return;
        if(line.size()>128)throw std::runtime_error("pad command exceeds 128 bytes");
        uint64_t sequence,hold;std::string buttons,extra;std::istringstream input(line);
        if(!(input>>sequence>>buttons>>hold)||(input>>extra)||!hold||hold>3600||tick>UINT64_MAX-hold)
            throw std::runtime_error("pad command must be SEQUENCE BUTTON[+BUTTON] HOLD_TICKS (1..3600)");
        uint32_t mask=0;
        const char *names[]={"SELECT","L3","R3","START","UP","RIGHT","DOWN","LEFT",
                             "L2","R2","L1","R1","TRIANGLE","CIRCLE","CROSS","SQUARE"};
        if(buttons!="NONE"){
            size_t start=0;
            do{
                const auto end=buttons.find('+',start);
                const auto name=buttons.substr(start,end==std::string::npos?end:end-start);
                unsigned bit=0;while(bit<16&&name!=names[bit])++bit;
                if(bit==16)throw std::runtime_error("unknown pad command button: "+name);
                mask|=1u<<bit;
                if(end==std::string::npos)break;
                start=end+1;
            }while(true);
        }
        if(sequence<=sequence_)return;
        sequence_=sequence;until_=tick+hold;mask_=mask;edge_=mask;
    }
    void merge(uint64_t tick,uint32_t &held,uint32_t &pressed){
        if(tick<until_){held|=mask_;pressed|=edge_;}
        edge_=0;
    }
    void sample(const std::filesystem::path &path,uint64_t tick,uint32_t &held,uint32_t &pressed){
        if(path.empty())return;
        const auto now=std::chrono::steady_clock::now();
        if(now>=next_){
            next_=now+std::chrono::milliseconds(50);
            std::ifstream input(path,std::ios::binary);
            if(input){char buffer[129];input.read(buffer,sizeof(buffer));
                accept(std::string(buffer,static_cast<size_t>(input.gcount())),tick);}
        }
        merge(tick,held,pressed);
    }
};
}
