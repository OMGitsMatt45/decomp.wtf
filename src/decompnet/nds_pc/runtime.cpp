// SPDX-License-Identifier: MIT. Original decomp.wtf experimental DS runtime.
#include "runtime.hpp"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace nds {
std::string hex(uint32_t address) {
    std::ostringstream stream;
    stream << "0x" << std::hex << std::setw(8) << std::setfill('0') << address;
    return stream.str();
}
uint32_t sign_extend(uint32_t value, unsigned bits) {
    const auto mask = (1u << bits) - 1u;
    value &= mask;
    return value & (1u << (bits-1)) ? value | ~mask : value;
}
Shift shift(uint32_t value, unsigned kind, unsigned amount, bool carry, bool by_register) {
    if (by_register && amount == 0) return {value,carry};
    if (!by_register && amount == 0) {
        if (kind == 0) return {value,carry};
        if (kind == 3) return {(uint32_t(carry)<<31) | (value>>1), bool(value&1)};
        amount = 32;
    }
    switch (kind) {
    case 0:
        if (amount > 32) return {0,false};
        if (amount == 32) return {0,bool(value&1)};
        return {uint32_t(value<<amount),bool((value>>(32-amount))&1)};
    case 1:
        if (amount > 32) return {0,false};
        if (amount == 32) return {0,bool(value>>31)};
        return {value>>amount,bool((value>>(amount-1))&1)};
    case 2: {
        const bool sign = value>>31;
        if (amount >= 32) return {sign ? 0xffffffffu : 0u,sign};
        return {(value>>amount) | (sign ? 0xffffffffu<<(32-amount) : 0u),bool((value>>(amount-1))&1)};
    }
    case 3:
        amount %= 32;
        if (!amount) return {value,bool(value>>31)};
        return {(value>>amount) | (value<<(32-amount)),bool((value>>(amount-1))&1)};
    }
    throw std::runtime_error("invalid generated shift operation");
}
void logic_flags(Cpu& c, uint32_t value, bool carry) {
    c.n = value>>31; c.z = value==0; c.carry = carry;
}
uint32_t add(Cpu& c, uint32_t a, uint32_t b, bool carry_in, bool flags) {
    const auto wide = uint64_t(a)+uint64_t(b)+uint32_t(carry_in);
    const auto value = uint32_t(wide);
    if (flags) {
        logic_flags(c,value,bool(wide>>32));
        c.v = ((~(a^b) & (a^value))>>31) != 0;
    }
    return value;
}
bool condition(const Cpu& c, unsigned cc) {
    switch(cc) {
    case 0:return c.z; case 1:return !c.z;
    case 2:return c.carry; case 3:return !c.carry;
    case 4:return c.n; case 5:return !c.n;
    case 6:return c.v; case 7:return !c.v;
    case 8:return c.carry && !c.z; case 9:return !c.carry || c.z;
    case 10:return c.n==c.v; case 11:return c.n!=c.v;
    case 12:return !c.z && c.n==c.v; case 13:return c.z || c.n!=c.v;
    case 14:return true;
    }
    throw std::runtime_error("invalid generated condition");
}
Runtime::Runtime(std::filesystem::path assets):
    ram_(0x400000),shared_(0x8000),iwram_(0x10000),assets_(std::move(assets)) {
    for (unsigned i=0;i<2;++i) {
        cpu[i].id=i; cpu[i].pc=entries[i]&~1u; cpu[i].thumb=entries[i]&1;
        cpu[i].r[13]=stacks[i]; cpu[i].r[14]=stop_pc;
    }
    for (unsigned i=0;i<module_count;++i) if(modules[i].overlay<0) load(modules[i]);
}
uint8_t* Runtime::memory(uint32_t address, unsigned size) {
    struct Region { uint32_t base; std::vector<uint8_t>* data; };
    for (auto region : {Region{0x02000000u,&ram_},Region{0x03000000u,&shared_},Region{0x03800000u,&iwram_}}) {
        const uint64_t offset=uint64_t(address)-region.base;
        if (address>=region.base && offset+size<=region.data->size()) return region.data->data()+offset;
    }
    throw std::runtime_error("unimplemented DS memory/device access at "+hex(address));
}
void Runtime::writable(uint32_t address, unsigned size) {
    for (unsigned i=0;i<code_range_count;++i) {
        const auto& r=code_ranges[i];
        if(uint64_t(address)<uint64_t(r.address)+r.size && uint64_t(r.address)<uint64_t(address)+size)
            throw std::runtime_error("write to statically translated code at "+hex(address));
    }
}
uint8_t Runtime::read8(uint32_t a) {return *memory(a,1);}
uint16_t Runtime::read16(uint32_t a) {
    if(a&1)throw std::runtime_error("unaligned halfword access at "+hex(a));
    const auto* p=memory(a,2); return uint16_t(p[0]) | uint16_t(p[1])<<8;
}
uint32_t Runtime::read32(uint32_t a) {
    if(a&3)throw std::runtime_error("unaligned word access at "+hex(a));
    const auto* p=memory(a,4); return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
void Runtime::write8(uint32_t a,uint32_t v) {writable(a,1); *memory(a,1)=uint8_t(v);}
void Runtime::write16(uint32_t a,uint32_t v) {
    if(a&1)throw std::runtime_error("unaligned halfword write at "+hex(a));
    writable(a,2);auto* p=memory(a,2); p[0]=uint8_t(v);p[1]=uint8_t(v>>8);
}
void Runtime::write32(uint32_t a,uint32_t v) {
    if(a&3)throw std::runtime_error("unaligned word write at "+hex(a));
    writable(a,4);auto* p=memory(a,4);for(unsigned i=0;i<4;++i)p[i]=uint8_t(v>>(8*i));
}
void Runtime::branch(Cpu& c,uint32_t target,bool exchange) {
    if(exchange)c.thumb=target&1;
    c.pc=target & (c.thumb ? ~1u : ~3u);
    c.halted=c.pc==stop_pc;
}
void Runtime::load(const Module& m) {
    std::ifstream file(assets_/m.asset,std::ios::binary);
    if(!file)throw std::runtime_error("missing module asset; run tools/extract_assets.py first");
    std::vector<uint8_t> bytes(m.size);
    file.read(reinterpret_cast<char*>(bytes.data()),m.size);
    if(file.gcount()!=m.size || file.peek()!=std::char_traits<char>::eof())
        throw std::runtime_error("module asset size differs: "+std::string(m.name));
    for(unsigned i=0;i<code_range_count;++i) {
        const auto& r=code_ranges[i];
        if(r.cpu==m.cpu && r.overlay==m.overlay && r.address>=m.address &&
           uint64_t(r.address)+r.size<=uint64_t(m.address)+m.size &&
           !std::equal(r.expected,r.expected+r.size,bytes.data()+(r.address-m.address)))
            throw std::runtime_error("module code differs from static translation: "+std::string(m.name));
    }
    std::copy(bytes.begin(),bytes.end(),memory(m.address,m.size));
    if(m.bss_size)std::fill_n(memory(m.bss_address,m.bss_size),m.bss_size,0);
}
void Runtime::load_overlay(unsigned processor,unsigned id) {
    if(processor>1 || id>0xffffff)throw std::runtime_error("invalid overlay processor or ID");
    for(unsigned i=0;i<module_count;++i) {
        const auto& m=modules[i];
        if(m.cpu==processor && m.overlay==int(id)) {
            load(m);active_overlay[processor]=int(id);overlay_loads.push_back((processor<<24)|id);return;
        }
    }
    throw std::runtime_error("overlay has no reviewed static translation");
}
void Runtime::load_save(const std::filesystem::path& path) {
    if(path.empty())return;
    if(!save_size)throw std::runtime_error("profile declares no save region");
    if(!std::filesystem::exists(path))return;
    if(std::filesystem::file_size(path)!=save_size)throw std::runtime_error("save file size differs from profile");
    std::ifstream file(path,std::ios::binary);
    std::vector<uint8_t> bytes(save_size);file.read(reinterpret_cast<char*>(bytes.data()),save_size);
    if(!file)throw std::runtime_error("could not read save");
    writable(save_address,save_size);
    std::copy(bytes.begin(),bytes.end(),memory(save_address,save_size));
}
void Runtime::write_save(const std::filesystem::path& path) {
    if(path.empty())return;
    auto temporary=path;temporary+=".tmp";
    if(std::filesystem::exists(temporary))throw std::runtime_error("save temporary file already exists");
    std::ofstream file(temporary,std::ios::binary|std::ios::trunc);
    file.write(reinterpret_cast<const char*>(memory(save_address,save_size)),save_size);
    file.close();if(!file)throw std::runtime_error("could not write save");
#ifdef _WIN32
    if(!MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("could not publish save");
#else
    std::filesystem::rename(temporary,path);
#endif
}
void Runtime::run(uint64_t max_steps) {
    while(!cpu[0].halted || !cpu[1].halted) {
        for(auto& c:cpu) {
            if(c.halted)continue;
            if(steps++>=max_steps)throw std::runtime_error("instruction budget exceeded");
            if(service(*this,c))continue;
            const bool found=c.id==0 ? dispatch_arm9(*this,c) : dispatch_arm7(*this,c);
            if(!found)throw std::runtime_error("untranslated ARM"+std::to_string(c.id==0?9:7)+
                (c.thumb ? " Thumb" : " ARM")+" target at "+hex(c.pc));
        }
    }
}
}
