#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace ds_host {
// Bounded memory-program protocol. This never decodes or executes ARM code.
// Callbacks supply a read view and a transaction's proposed memory writes.
struct MemoryProgram {
    struct Line {uint32_t command,value;};
    std::vector<Line> lines;
    static constexpr size_t maximum_steps=65536,maximum_bytes=65536;

    void validate() const {
        if(lines.empty()||lines.size()>8192)throw std::runtime_error("invalid memory program length");
        for(size_t i=0;i<lines.size();++i) {
            const auto [a,b]=lines[i];const unsigned op=a>>28,sub=(a>>24)&15;
            if(op==14) {
                const uint64_t count=(uint64_t(b)+7)/8;
                if(b>maximum_bytes||count>lines.size()-i-1)throw std::runtime_error("truncated memory program payload");
                i+=size_t(count);
            } else if(op==12) {
                if(sub!=0||b>=maximum_steps)throw std::runtime_error("unsupported memory program loop");
            } else if(op==13) {
                if(sub>12||sub==11||(a&0xffffffu)!=0)throw std::runtime_error("unsupported memory program register operation");
            } else if(op>11)throw std::runtime_error("unsupported memory program operation");
        }
    }

    template<class Read,class Write> void run(Read read,Write write) const {
        uint32_t offset=0,data=0,conditions=0,loop_conditions=0;
        bool condition=true,loop_condition=true;
        size_t cursor=0,loop_start=0,steps=0,bytes=0;
        uint32_t repeats=0;
        auto store=[&](unsigned width,uint32_t address,uint32_t value) {
            bytes+=width;if(bytes>maximum_bytes)throw std::runtime_error("memory program write budget exceeded");
            write(width,address,value);
        };
        while(cursor<lines.size()) {
            if(++steps>maximum_steps)throw std::runtime_error("memory program step budget exceeded");
            const auto [a,b]=lines[cursor++];const unsigned op=a>>28,sub=(a>>24)&15;
            const uint32_t address=a&0xfffffff;
            if(op==14) {
                const size_t count=(uint64_t(b)+7)/8;
                if(count>lines.size()-cursor)throw std::runtime_error("truncated memory program payload");
                if(condition)for(uint32_t j=0;j<b;++j) {
                    const auto& pair=lines[cursor+j/8];
                    const uint32_t word=(j%8<4)?pair.command:pair.value;
                    store(1,address+offset+j,(word>>(8*(j%4)))&255);
                }
                cursor+=count;continue;
            }
            // In this protocol a skipped conditional does not push another
            // condition. D0/D1/D2 still unwind or flush a skipped block.
            if(!condition&&!(op==13&&sub<=2))continue;
            if(op<=2){store(4u>>op,address+offset,b);continue;}
            if(op>=3&&op<=10) {
                const auto value=read(op<=6?4:2,address?address:offset);
                conditions=(conditions<<1)|uint32_t(condition);
                if(op==3)condition=b>value;
                else if(op==4)condition=b<value;
                else if(op==5)condition=b==value;
                else if(op==6)condition=b!=value;
                else {
                    const uint32_t masked=value&(~(b>>16)&65535),test=b&65535;
                    condition=op==7?test>masked:op==8?test<masked:op==9?test==masked:test!=masked;
                }
                continue;
            }
            if(op==11){offset=read(4,address+offset);continue;}
            if(op==12){loop_start=cursor;repeats=b;loop_condition=condition;loop_conditions=conditions;continue;}
            if(op!=13)throw std::runtime_error("unsupported memory program operation");
            switch(sub) {
            case 0:condition=(conditions&1)!=0;conditions>>=1;break;
            case 1:case 2:
                if(repeats){--repeats;cursor=loop_start;}
                else if(sub==1){condition=loop_condition;conditions=loop_conditions;}
                else{offset=data=conditions=0;condition=true;}
                break;
            case 3:offset=b;break;
            case 4:data+=b;break;
            case 5:data=b;break;
            case 6:case 7:case 8:{const unsigned width=sub==6?4:sub==7?2:1;store(width,b+offset,data);offset+=width;break;}
            case 9:data=read(4,b+offset);break;
            case 10:data=read(2,b+offset);break;
            case 12:offset+=b;break;
            default:throw std::runtime_error("unsupported memory program register operation");
            }
        }
    }
};
}
