// SPDX-License-Identifier: CC0-1.0
// Original IRX and R3000A fixture. No game, BIOS or SDK payload.
#include "MiniTest.h"
#include "lle/iop.h"
#include <array>
#include <cstring>
#include <memory>

namespace {
using namespace ps2x::iop::lle;
void put16(std::vector<uint8_t>& file, size_t at, uint16_t value) {
    file[at]=uint8_t(value);file[at+1]=uint8_t(value>>8);
}
void put32(std::vector<uint8_t>& file, size_t at, uint32_t value) {
    for(unsigned i=0;i<4;++i)file[at+i]=uint8_t(value>>(i*8));
}
uint32_t word(const std::vector<uint8_t>& bytes, size_t at) {
    return bytes[at]|(uint32_t(bytes[at+1])<<8)|(uint32_t(bytes[at+2])<<16)|(uint32_t(bytes[at+3])<<24);
}
std::vector<uint8_t> module() {
    std::vector<uint8_t> file(0x200);
    std::memcpy(file.data(),"\x7f" "ELF\1\1\1",7);
    put16(file,0x10,0xff80);put16(file,0x12,8);put32(file,0x14,1);
    put32(file,0x1c,0x34);put32(file,0x20,0x180);
    put16(file,0x28,0x34);put16(file,0x2a,32);put16(file,0x2c,2);
    put16(file,0x2e,40);put16(file,0x30,1);
    put32(file,0x34,1);put32(file,0x38,0x100);
    put32(file,0x44,44);put32(file,0x48,60);put32(file,0x4c,7);put32(file,0x50,16);
    put32(file,0x54,0x70000080);put32(file,0x58,0x80);put32(file,0x64,39);
    put32(file,0x68,39);put32(file,0x6c,4);put32(file,0x70,4);
    put32(file,0x8c,40);put32(file,0x90,4);put32(file,0x94,16);
    put16(file,0x98,0x101);std::memcpy(file.data()+0x9a,"original-iop",13);
    // Record argc and the first character of argv[0] in private IOP RAM, then
    // return MODULE_RESIDENT_END. NOPs respect R3000A load delay slots.
    const uint32_t code[]={0x3c08001f,0xad040000,0x8caa0000,0,0x914b0000,
                           0,0xad0b0004,0x24020000,0x03e00008,0};
    for(unsigned i=0;i<10;++i)put32(file,0x100+i*4,code[i]);
    put32(file,0x128,4); // module-relative data pointer
    put32(file,0x140,40);put32(file,0x144,2); // R_MIPS_32 relocation
    put32(file,0x184,9);put32(file,0x190,0x140);put32(file,0x194,8);put32(file,0x1a4,8);
    return file;
}
struct Link: EeLink {
    std::vector<std::string> messages;
    bool readEe(uint32_t,void*,uint32_t) override{return false;}
    bool writeEe(uint32_t,const void*,uint32_t) override{return false;}
    bool eeServer(uint32_t) override{return false;}
    void log(const std::string& text) override{messages.push_back(text);}
};
}

void register_decomp_irx_tests() {
    MiniTest::Case("OriginalIrx",[](TestCase& tc) {
        tc.Run("original IRX executes its R3000A entry with loader arguments",[](TestCase& t) {
            Link link;auto iop=std::make_unique<Iop>(link);
            const auto id=iop->loadModule(module(),"test.irx",{"one","two"});
            std::array<uint32_t,2> observed{};iop->readMemory(0x1f0000,observed.data(),8);
            t.IsTrue(id>0,"a resident original module must load successfully");
            t.Equals(observed[0],3u,"the guest entry receives path plus both arguments");
            t.Equals(observed[1],uint32_t('t'),"the guest follows argv[0] through real IOP memory");
        });
        tc.Run("IRX relocation adjusts original pointers and zeros BSS",[](TestCase& t) {
            IrxImage image;std::string error;std::vector<IrxImport> imports;
            t.IsTrue(parseIrx(module(),image,error),"original ELF32 MIPS metadata parses");
            std::vector<uint8_t> ram(0x4000,0xaa);
            t.IsTrue(relocateIrx(image,ram.data(),uint32_t(ram.size()),0x1000,imports,error),"the original relocation succeeds");
            t.Equals(word(ram,0x1028),0x1004u,"R_MIPS_32 retains the correct relocated address");
            bool zero=true;for(unsigned n=44;n<60;++n)zero=zero&&ram[0x1000+n]==0;
            t.IsTrue(zero,"the module's entire BSS is zero initialized");
            t.Equals(ram[0xfff],uint8_t(0xaa),"memory before the image stays untouched");
            t.Equals(ram[0x103c],uint8_t(0xaa),"memory after the image stays untouched");
        });
        tc.Run("IRX relocation rejects unsupported entries and out of memory",[](TestCase& t) {
            IrxImage image;std::string error;std::vector<IrxImport> imports;
            parseIrx(module(),image,error);std::vector<uint8_t> ram(0x4000,0xaa);
            t.IsFalse(relocateIrx(image,ram.data(),uint32_t(ram.size()),0x3ff0,imports,error),"a truncated destination fails");
            t.Equals(ram.back(),uint8_t(0xaa),"a rejected destination is not written");
            image.relocations[0].type=255;
            t.IsFalse(relocateIrx(image,ram.data(),uint32_t(ram.size()),0x1000,imports,error),"unknown relocation types cannot be ignored");
        });
        tc.Run("IRX parser rejects foreign architecture and byte order",[](TestCase& t) {
            for(unsigned variant=0;variant<3;++variant) {
                auto file=module();if(variant==0)file[4]=2;else if(variant==1)file[5]=2;else put16(file,0x12,62);
                IrxImage image;std::string error;
                t.IsFalse(parseIrx(file,image,error),"only ELF32 little-endian MIPS is an IOP module");
            }
        });
        tc.Run("IRX parser rejects truncated metadata and invalid entry",[](TestCase& t) {
            for(unsigned variant=0;variant<2;++variant) {
                auto file=module();if(variant==0)put32(file,0x58,0x2000);else put32(file,0x84,0x1000);
                IrxImage image;std::string error;
                t.IsFalse(parseIrx(file,image,error),"malformed module metadata cannot reach execution");
            }
        });
        tc.Run("IRX parser rejects incomplete relocation records",[](TestCase& t) {
            auto file=module();put32(file,0x194,7);
            IrxImage image;std::string error;
            t.IsFalse(parseIrx(file,image,error),"an incomplete REL record is not silently skipped");
        });
    });
}
