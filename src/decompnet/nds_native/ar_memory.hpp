#pragma once
#include "ar_program.hpp"
#include <dsr/machine.h>
#include <algorithm>
#include <map>
#include <set>

namespace ds_host {
class MemoryProgramHost {
    std::vector<std::pair<uint32_t,uint64_t>> blocked;
    static void ram(uint32_t address,unsigned width) {
        if(address<0x02000000||uint64_t(address)+width>0x02400000)
            throw std::runtime_error("memory program address is outside main RAM");
    }
    void data_address(uint32_t address) const {
        const auto found=std::upper_bound(blocked.begin(),blocked.end(),address,
            [](uint32_t a,const auto& range){return a<range.first;});
        if(found!=blocked.begin()&&address<std::prev(found)->second)
            throw std::runtime_error("memory program has no compiled alternative for this code address");
    }
    static uint32_t physical(dsr::Machine& machine,unsigned width,uint32_t address,dsr::CpuId cpu=dsr::CpuId::Arm9) {
        return width==1?machine.read8(cpu,address):width==2?machine.read16(cpu,address):machine.read32(cpu,address);
    }
public:
    explicit MemoryProgramHost(const dsr::MachineConfig& config) {
        auto add=[&](uint32_t first,uint64_t end){if(first<end)blocked.emplace_back(first,end);};
        for(const auto table:{config.arm9_table,config.arm7_table})
            for(size_t i=0;i<table.count;++i)add(table.entries[i].addr,uint64_t(table.entries[i].addr)+table.entries[i].size);
        for(const auto table:{config.arm9_regions,config.arm7_regions})for(size_t i=0;i<table.count;++i) {
            const auto& region=table.entries[i];uint32_t start=region.begin;
            std::vector<std::pair<uint32_t,uint64_t>> data;
            for(size_t j=0;j<region.data_range_count;++j) {
                const auto& range=region.data_ranges[j];data.emplace_back(range.begin,uint64_t(range.begin)+range.size);
            }
            std::sort(data.begin(),data.end());
            for(const auto& range:data){add(start,range.first);start=uint32_t(std::max(uint64_t(start),range.second));}
            add(start,uint64_t(region.begin)+region.size);
        }
        std::sort(blocked.begin(),blocked.end());
        std::vector<std::pair<uint32_t,uint64_t>> merged;
        for(const auto& range:blocked) {
            if(!merged.empty()&&range.first<=merged.back().second)merged.back().second=std::max(merged.back().second,range.second);
            else merged.push_back(range);
        }
        blocked=std::move(merged);
    }
    // All reads/writes are planned before any guest data or selection changes.
    // Invalid dynamic pointers or unavailable modules discard the whole plan.
    size_t apply(const MemoryProgram& program,dsr::Machine& machine,uint32_t owner) const {
        if(!owner)throw std::runtime_error("memory program owner must be nonzero");
        const auto& choices=machine.instruction_choice_table();
        std::map<uint32_t,uint8_t> proposed;
        auto byte=[&](uint32_t address) -> uint32_t {
            if(const auto p=proposed.find(address);p!=proposed.end())return p->second;
            for(size_t i=0;i<choices.count;++i) {
                const auto& site=choices.entries[i];
                if(address>=site.address&&uint64_t(address)<uint64_t(site.address)+site.width&&
                   physical(machine,site.width,site.address,site.cpu)==site.original)
                    return (machine.instruction_choice(i,site.original)>>(8*(address-site.address)))&255;
            }
            return machine.read8(dsr::CpuId::Arm9,address);
        };
        auto read=[&](unsigned width,uint32_t address) -> uint32_t {
            if((address==0x04000130||address==0x04000136)&&width==2)
                return machine.read16(dsr::CpuId::Arm7,address);
            ram(address,width);uint32_t value=0;
            for(unsigned i=0;i<width;++i)value|=byte(address+i)<<(8*i);
            return value;
        };
        program.run(read,[&](unsigned width,uint32_t address,uint32_t value) {
            ram(address,width);
            for(unsigned i=0;i<width;++i)proposed[address+i]=uint8_t(value>>(8*i));
        });
        std::set<size_t> touched;
        std::vector<std::pair<uint32_t,uint8_t>> data;
        for(const auto& [address,value]:proposed) {
            bool managed=false;
            for(size_t i=0;i<choices.count;++i) {
                const auto& site=choices.entries[i];
                if(address>=site.address&&uint64_t(address)<uint64_t(site.address)+site.width&&
                   physical(machine,site.width,site.address,site.cpu)==site.original){touched.insert(i);managed=true;}
            }
            if(!managed&&value!=physical(machine,1,address)){data_address(address);data.emplace_back(address,value);}
        }
        std::vector<std::pair<size_t,uint32_t>> selections;
        for(const size_t index:touched) {
            const auto& site=choices.entries[index];const auto value=read(site.width,site.address);
            bool allowed=value==site.original;
            for(size_t j=0;j<site.value_count;++j)allowed|=value==site.values[j];
            if(!allowed)throw std::runtime_error("memory program requested an uncompiled instruction value");
            selections.emplace_back(index,value);
        }
        for(const auto& [index,value]:selections)
            if(!machine.select_instruction_choice(index,value,owner))throw std::runtime_error("compiled selection rejected");
        for(const auto& [address,value]:data)machine.write8(dsr::CpuId::Arm9,address,value);
        return selections.size()+data.size();
    }
};
}
