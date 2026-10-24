// SPDX-License-Identifier: MIT. Streaming SHA-256 for generated input identity.
#pragma once
#include <array>
#include <bit>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>

inline std::string input_sha256(const std::filesystem::path& path) {
    constexpr uint32_t k[]={
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    std::array<uint32_t,8> h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    const auto block=[&](const uint8_t* bytes) {
        uint32_t w[64];
        for(unsigned i=0;i<16;++i)w[i]=(uint32_t(bytes[i*4])<<24)|(uint32_t(bytes[i*4+1])<<16)|(uint32_t(bytes[i*4+2])<<8)|bytes[i*4+3];
        for(unsigned i=16;i<64;++i) {
            const auto a=std::rotr(w[i-15],7)^std::rotr(w[i-15],18)^(w[i-15]>>3);
            const auto b=std::rotr(w[i-2],17)^std::rotr(w[i-2],19)^(w[i-2]>>10);
            w[i]=w[i-16]+a+w[i-7]+b;
        }
        auto v=h;
        for(unsigned i=0;i<64;++i) {
            const auto a=std::rotr(v[4],6)^std::rotr(v[4],11)^std::rotr(v[4],25);
            const auto b=(v[4]&v[5])^(~v[4]&v[6]);
            const auto t=v[7]+a+b+k[i]+w[i];
            const auto c=std::rotr(v[0],2)^std::rotr(v[0],13)^std::rotr(v[0],22);
            const auto d=(v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]);
            for(unsigned j=7;j>0;--j)v[j]=v[j-1];
            v[4]+=t;v[0]=t+c+d;
        }
        for(unsigned i=0;i<8;++i)h[i]+=v[i];
    };
    std::ifstream file(path,std::ios::binary);
    if(!file)throw std::runtime_error("missing DS assets; run tools/extract_assets.py first");
    std::array<uint8_t,128> tail{};uint64_t size=0;size_t used=0;
    for(;;) {
        file.read(reinterpret_cast<char*>(tail.data()),64);
        used=size_t(file.gcount());size+=used;
        if(used<64)break;
        block(tail.data());
    }
    if(file.bad())throw std::runtime_error("could not read DS assets");
    for(size_t i=used;i<tail.size();++i)tail[i]=0;
    tail[used]=0x80;
    const size_t bytes=used<56 ? 64 : 128;
    for(unsigned i=0;i<8;++i)tail[bytes-1-i]=uint8_t((size*8)>>(i*8));
    block(tail.data());if(bytes==128)block(tail.data()+64);
    std::ostringstream out;out<<std::hex<<std::setfill('0');
    for(auto value:h)out<<std::setw(8)<<value;
    return out.str();
}
