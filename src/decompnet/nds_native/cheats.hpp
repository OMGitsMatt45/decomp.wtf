#pragma once
#include "ar_memory.hpp"
#include <dsr/machine.h>
#include <dsr/rt.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace ds_host {
// ROM-bound data operations and bounded memory programs. Instruction changes
// select reviewed C++ alternatives while preserving original guest code bytes.
class Cheats {
    std::unique_ptr<MemoryProgramHost> program_host;
    unsigned light_level=3;
    uint16_t previous_light_keys=0xffff;
public:
    struct Operation { unsigned width; uint32_t address,value; bool copy; };
    struct Guard { uint32_t address,minimum,maximum; };
    struct Entry {
        std::string name;
        std::vector<Operation> operations;
        std::vector<Guard> guards;
        bool enabled=false;
        MemoryProgram program;
        std::string group,action;
        bool was_enabled=false;
    };
    std::vector<Entry> entries;
    uint64_t applications=0,menu_openings=0,menu_frames=0;
    uint64_t program_rejections=0;
    std::string last_program_error;

    static uint32_t number(const std::string& text) {
        size_t end=0;
        if(text.empty()||text.front()=='-')throw std::runtime_error("invalid cheat number");
        const auto value=std::stoull(text,&end,0);
        if(end!=text.size()||value>0xffffffffull)throw std::runtime_error("invalid cheat number");
        return uint32_t(value);
    }
    static void address(uint32_t value,unsigned width,const dsr::MachineConfig& config,bool write) {
        if(value<0x02000000u||uint64_t(value)+width>0x02400000ull||value%width)
            throw std::runtime_error("cheats require aligned main RAM data addresses");
        if(!write)return;
        for(const auto table:{config.arm9_table,config.arm7_table})
            for(size_t i=0;i<table.count;++i) {
                const auto& entry=table.entries[i];
                if(uint64_t(value)<uint64_t(entry.addr)+entry.size&&uint64_t(value)+width>entry.addr)
                    throw std::runtime_error("cheat touches translated code; requires a native source patch");
            }
        for(const auto table:{config.arm9_regions,config.arm7_regions})
            for(size_t i=0;i<table.count;++i) {
                const auto& entry=table.entries[i];
                if(uint64_t(value)<uint64_t(entry.begin)+entry.size&&uint64_t(value)+width>entry.begin) {
                    bool data=false;
                    for(size_t j=0;j<entry.data_range_count;++j) {
                        const auto& range=entry.data_ranges[j];
                        if(value>=range.begin&&uint64_t(value)+width<=uint64_t(range.begin)+range.size)data=true;
                    }
                    if(!data)throw std::runtime_error("cheat touches translated code; requires a native source patch");
                }
            }
    }
    void load(const std::filesystem::path& path,const std::string& sha256,const dsr::MachineConfig& config) {
        std::ifstream file(path);
        if(!file)throw std::runtime_error("could not read cheat catalog");
        std::vector<Entry> parsed;
        std::string line;bool bound=false,open=false;
        while(std::getline(file,line)) {
            std::istringstream row(line);std::string kind;row>>kind;
            if(kind.empty()||kind.front()=='#')continue;
            if(!bound) {
                std::string digest;row>>digest;
                if(kind!="rom"||digest!=sha256)throw std::runtime_error("cheat catalog ROM SHA-256 mismatch");
                bound=true;
            } else if(kind=="choices") {
                std::string digest;row>>digest;
                if(!row||!config.instruction_choices.sha256||digest!=config.instruction_choices.sha256)
                    throw std::runtime_error("cheat catalog compiled-choice SHA-256 mismatch");
            } else if(kind=="cheat") {
                if(open)throw std::runtime_error("missing cheat end");
                std::string name;row>>std::quoted(name);
                if(!row||name.empty()||name.size()>48||name.find_first_of("\r\n\t")!=std::string::npos)
                    throw std::runtime_error("invalid cheat name");
                for(const auto& entry:parsed)if(entry.name==name)throw std::runtime_error("duplicate cheat name");
                parsed.push_back({name,{},{},false});open=true;
            } else if(kind=="end") {
                if(!open||(parsed.back().operations.empty()&&parsed.back().program.lines.empty()&&parsed.back().action.empty()))throw std::runtime_error("empty or unmatched cheat end");
                if(!parsed.back().program.lines.empty())parsed.back().program.validate();
                open=false;
            } else if(kind=="group"||kind=="action") {
                if(!open)throw std::runtime_error("cheat metadata outside an entry");
                std::string value;row>>std::quoted(value);
                if(!row||value.empty()||value.size()>80)throw std::runtime_error("invalid cheat metadata");
                if(kind=="group")parsed.back().group=value;
                else if(value=="backlight")parsed.back().action=value;
                else throw std::runtime_error("unsupported native cheat action");
            } else {
                if(!open)throw std::runtime_error("cheat operation outside an entry");
                std::string first,second,third;row>>first>>second;
                if(!row)throw std::runtime_error("incomplete cheat operation");
                const auto a=number(first),b=number(second);
                if(kind=="ar") {
                    parsed.back().program.lines.push_back({a,b});
                } else if(kind=="when16") {
                    row>>third;if(!row)throw std::runtime_error("incomplete cheat guard");
                    const auto high=number(third);
                    if(b>high||high>65535)throw std::runtime_error("invalid cheat guard bounds");
                    address(a,2,config,false);parsed.back().guards.push_back({a,b,high});
                } else if(kind=="copy16") {
                    address(a,2,config,false);address(b,2,config,true);
                    parsed.back().operations.push_back({2,b,a,true});
                } else {
                    const unsigned width=kind=="write8"?1:kind=="write16"?2:kind=="write32"?4:0;
                    if(!width)throw std::runtime_error("unsupported cheat operation");
                    if(width<4&&b>=(1u<<(width*8)))throw std::runtime_error("cheat value exceeds write width");
                    address(a,width,config,true);parsed.back().operations.push_back({width,a,b,false});
                }
            }
            std::string extra;if(row>>extra)throw std::runtime_error("unexpected cheat fields");
        }
        if(!bound||open)throw std::runtime_error("incomplete cheat catalog");
        entries=std::move(parsed);
        program_host=std::make_unique<MemoryProgramHost>(config);
    }
    void toggle(size_t index) {
        if(index>=entries.size())throw std::runtime_error("unknown cheat index");
        auto& entry=entries[index];entry.enabled=!entry.enabled;
        if(entry.enabled&&!entry.group.empty())
            for(size_t i=0;i<entries.size();++i)if(i!=index&&entries[i].group==entry.group)entries[i].enabled=false;
    }
    void enable(const std::string& name) {
        for(size_t i=0;i<entries.size();++i)if(entries[i].name==name){if(!entries[i].enabled)toggle(i);return;}
        throw std::runtime_error("unknown cheat name: "+name);
    }
    float brightness() const {
        for(const auto& entry:entries)if(entry.enabled&&entry.action=="backlight")return .4f+.2f*light_level;
        return 1.f;
    }
    size_t enabled_count() const {
        size_t count=0;for(const auto& entry:entries)count+=entry.enabled;return count;
    }
    void prepare(dsr::Machine& machine,bool before_boot=false) {
        // Clear disabled owners before applying any newly enabled conflicting
        // entry, regardless of their order in the catalog.
        for(size_t i=0;i<entries.size();++i) {
            auto& entry=entries[i];
            if(entry.was_enabled&&!entry.enabled)machine.clear_instruction_choices(uint32_t(i+1));
            entry.was_enabled=entry.enabled;
        }
        if(before_boot)for(size_t i=0;i<entries.size();++i) {
            const auto& entry=entries[i];
            if(!entry.enabled||entry.program.lines.empty())continue;
            bool ready=true;
            for(const auto& guard:entry.guards) {
                const auto value=machine.read16(dsr::CpuId::Arm9,guard.address);
                if(value<guard.minimum||value>guard.maximum){ready=false;break;}
            }
            if(ready)try{applications+=program_host->apply(entry.program,machine,uint32_t(i+1));}
                catch(const std::runtime_error& error){++program_rejections;last_program_error=error.what();}
        }
    }
    void apply(dsr::Machine& machine) {
        constexpr auto cpu=dsr::CpuId::Arm9;
        prepare(machine);
        for(size_t i=0;i<entries.size();++i) {
            const auto& entry=entries[i];
            if(!entry.enabled)continue;
            bool ready=true;
            for(const auto& guard:entry.guards) {
                const auto value=machine.read16(cpu,guard.address);
                if(value<guard.minimum||value>guard.maximum){ready=false;break;}
            }
            if(!ready)continue;
            if(!entry.action.empty()) {
                const uint16_t keys=machine.read16(dsr::CpuId::Arm7,0x04000130);
                if((keys&0x304)==0) {
                    if(!(keys&0x40)&&(previous_light_keys&0x40)&&light_level<3)++light_level;
                    if(!(keys&0x80)&&(previous_light_keys&0x80)&&light_level>0)--light_level;
                }
                previous_light_keys=keys;
            }
            if(!entry.program.lines.empty()) {
                try {applications+=program_host->apply(entry.program,machine,uint32_t(i+1));}
                catch(const std::runtime_error& error) {++program_rejections;last_program_error=error.what();}
            }
            for(const auto& operation:entry.operations) {
                const auto value=operation.copy?machine.read16(cpu,operation.value):operation.value;
                switch(operation.width) {
                case 1:machine.write8(cpu,operation.address,uint8_t(value));break;
                case 2:machine.write16(cpu,operation.address,uint16_t(value));break;
                case 4:machine.write32(cpu,operation.address,value);break;
                }
                ++applications;
            }
        }
    }
};
}
