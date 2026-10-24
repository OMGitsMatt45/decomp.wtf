// SPDX-License-Identifier: MIT
// Read-only ISO/BIN file views for the source-shipped PS2 filesystem services.
#pragma once
#ifndef DECOMP_PS2_DISC_FILES_HPP
#define DECOMP_PS2_DISC_FILES_HPP
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <limits>
#include <mutex>
#include <span>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace decomp_ps2::disc {
struct Entry { std::string name; uint64_t lba, size; };
struct Slice { Entry entry; uint64_t position=0; unsigned sector=2048, skip=0; };
inline std::mutex mutex;
inline std::string image;
inline unsigned sector_size=2048, data_skip=0;
inline std::unordered_map<std::string,Entry> files;
inline std::unordered_map<FILE*,Slice> slices;
inline uint64_t read_bytes=0, read_calls=0;

inline std::string normalized(std::string name) {
    for(char &c:name) {
        if(c=='\\')c='/';
        else if(c>='a'&&c<='z')c=static_cast<char>(c-'a'+'A');
    }
    const auto colon=name.find(':');
    if(colon!=std::string::npos) {
        const auto device=name.substr(0,colon);
        if(device!="CDROM0" && device!="CDROM" && device!="CDFS")return {};
        name.erase(0,colon+1);
    }
    while(!name.empty()&&name.front()=='/')name.erase(0,1);
    if(name.ends_with(";1"))name.resize(name.size()-2);
    size_t start=0;
    while(start<name.size()) {
        const size_t end=name.find('/',start);
        const auto part=name.substr(start,end==std::string::npos?end:end-start);
        if(part.empty()||part=="."||part==".."||part.find(':')!=std::string::npos)return {};
        for(unsigned char c:part)if(c<32)return {};
        if(end==std::string::npos)break;
        start=end+1;
    }
    if(name.empty()||name.back()=='/')return {};
    return name;
}

inline bool disc_path(const char *path) {
    if(!path)return false;
    const std::string text(path);
    const auto colon=text.find(':');
    if(colon==std::string::npos)return false;
    std::string device=text.substr(0,colon);
    for(char &c:device)if(c>='a'&&c<='z')c=static_cast<char>(c-'a'+'A');
    return device=="CDROM0"||device=="CDROM"||device=="CDFS";
}

inline int physical_seek(FILE *file,int64_t offset,int origin) {
#ifdef _WIN32
    return _fseeki64(file,offset,origin);
#else
    return fseeko(file,static_cast<off_t>(offset),origin);
#endif
}
inline int64_t physical_tell(FILE *file) {
#ifdef _WIN32
    return _ftelli64(file);
#else
    return static_cast<int64_t>(ftello(file));
#endif
}

inline void mount(const std::filesystem::path &path,std::span<const Entry> entries,unsigned sector=2048,unsigned skip=0) {
    std::lock_guard lock(mutex);
    if(!slices.empty())throw std::runtime_error("cannot replace a PS2 disc with open file views");
    if((sector!=2048&&sector!=2352&&sector!=2336)||skip>sector-2048)
        throw std::runtime_error("invalid PS2 disc sector layout");
    const uint64_t length=std::filesystem::file_size(path);
    std::unordered_map<std::string,Entry> next;
    for(const auto &entry:entries) {
        const auto name=normalized(entry.name);
        if(name.empty()||next.contains(name))throw std::runtime_error("invalid or duplicate PS2 disc file");
        if(entry.lba>length/sector || entry.size>length)throw std::runtime_error("PS2 disc extent exceeds its image");
        if(entry.size) {
            const uint64_t last=(entry.size-1)/2048;
            if(last>length/sector-entry.lba || (entry.lba+last)*sector+skip+(entry.size-1)%2048>=length)
                throw std::runtime_error("PS2 disc extent exceeds its image");
        }
        next.emplace(name,Entry{name,entry.lba,entry.size});
    }
    image=path.string();files=std::move(next);sector_size=sector;data_skip=skip;read_bytes=read_calls=0;
}

inline FILE *open(const char *host,const char *mode,const char *guest) {
    if(!disc_path(guest))return std::fopen(host,mode);
    if(!mode||mode[0]!='r'||std::strchr(mode,'+')){errno=EROFS;return nullptr;}
    const auto name=normalized(guest);
    if(name.empty()){errno=ENOENT;return nullptr;}
    // Extracted owner files may override disc assets. Code identity guards
    // still apply to executable modules independently of asset placement.
    if(FILE *local=std::fopen(host,mode))return local;
    std::lock_guard lock(mutex);
    const auto found=files.find(name);
    if(found==files.end()||image.empty()){errno=ENOENT;return nullptr;}
    FILE *file=std::fopen(image.c_str(),"rb");
    if(file)slices.emplace(file,Slice{found->second,0,sector_size,data_skip});
    return file;
}

inline bool lookup(const std::string &path,Entry &entry) {
    const auto name=normalized(path);
    std::lock_guard lock(mutex);
    const auto found=files.find(name);
    if(found==files.end())return false;
    entry=found->second;return true;
}

inline bool mounted() {std::lock_guard lock(mutex);return !image.empty();}

inline bool read_sectors(uint32_t lba,uint32_t count,uint8_t *destination,size_t bytes) {
    std::lock_guard lock(mutex);
    if(image.empty()||bytes>uint64_t(count)*2048||(!destination&&bytes)){errno=EINVAL;return false;}
    FILE *file=std::fopen(image.c_str(),"rb");
    if(!file)return false;
    size_t done=0;
    while(done<bytes) {
        const uint64_t offset=(uint64_t(lba)+done/2048)*sector_size+data_skip;
        const size_t n=std::min<size_t>(bytes-done,2048);
        if(offset>INT64_MAX||physical_seek(file,static_cast<int64_t>(offset),SEEK_SET)||
            std::fread(destination+done,1,n,file)!=n)break;
        done+=n;
    }
    std::fclose(file);read_bytes+=done;++read_calls;return done==bytes;
}

inline size_t read(void *destination,size_t size,size_t count,FILE *file) {
    std::lock_guard lock(mutex);
    auto found=slices.find(file);
    if(found==slices.end())return std::fread(destination,size,count,file);
    if(!size||!count)return 0;
    if(count>std::numeric_limits<size_t>::max()/size){errno=EINVAL;return 0;}
    auto &slice=found->second;
    const uint64_t available=slice.position>=slice.entry.size?0:slice.entry.size-slice.position;
    size_t remaining=static_cast<size_t>(std::min<uint64_t>(size*count,available)),done=0;
    while(remaining) {
        const uint64_t block=slice.position/2048,within=slice.position%2048;
        const uint64_t physical=(slice.entry.lba+block)*slice.sector+slice.skip+within;
        if(physical>static_cast<uint64_t>(INT64_MAX)||physical_seek(file,static_cast<int64_t>(physical),SEEK_SET))break;
        const size_t chunk=slice.sector==2048?remaining:std::min<size_t>(remaining,2048-within);
        const size_t got=std::fread(static_cast<uint8_t*>(destination)+done,1,chunk,file);
        slice.position+=got;done+=got;remaining-=got;
        if(got!=chunk)break;
    }
    read_bytes+=done;++read_calls;
    return done/size;
}

inline int seek(FILE *file,int64_t offset,int origin) {
    std::lock_guard lock(mutex);
    auto found=slices.find(file);
    if(found==slices.end())return physical_seek(file,offset,origin);
    auto &slice=found->second;
    const uint64_t base=origin==SEEK_SET?0:origin==SEEK_CUR?slice.position:slice.entry.size;
    if((origin!=SEEK_SET&&origin!=SEEK_CUR&&origin!=SEEK_END)||base>static_cast<uint64_t>(INT64_MAX)||
        (offset>0&&base>static_cast<uint64_t>(INT64_MAX-offset))||
        (offset<0&&(offset==INT64_MIN||base<static_cast<uint64_t>(-offset)))){errno=EINVAL;return -1;}
    slice.position=static_cast<uint64_t>(static_cast<int64_t>(base)+offset);return 0;
}
inline int64_t tell(FILE *file) {
    std::lock_guard lock(mutex);
    auto found=slices.find(file);
    return found==slices.end()?physical_tell(file):static_cast<int64_t>(found->second.position);
}
inline int close(FILE *file) {
    std::lock_guard lock(mutex);slices.erase(file);return std::fclose(file);
}
}
#endif
