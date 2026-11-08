// SPDX-License-Identifier: MIT
// Read-only disc image and extracted file views for the PS2 filesystem services.
#pragma once
#ifndef DECOMP_PS2_DISC_FILES_HPP
#define DECOMP_PS2_DISC_FILES_HPP
#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <mutex>
#include <span>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace decomp_ps2::disc {
struct Entry { std::string name; uint64_t lba, size; };
struct Slice { Entry entry; uint64_t position=0; unsigned sector=2048, skip=0; };
struct Extent {
    std::filesystem::path path;
    uint64_t lba, size;

    uint64_t end_sector() const { return lba + (size + 2047) / 2048; }
};
inline std::mutex mutex;
inline std::filesystem::path image;
inline std::unordered_map<std::string,std::filesystem::path> extracted_files;
inline std::vector<Extent> extracted_extents;
inline uint64_t extracted_sector_count=0;
inline uint64_t unmapped_reads=0;
inline unsigned sector_size=2048, data_skip=0;
inline std::unordered_map<std::string,Entry> files;
inline std::unordered_map<FILE*,Slice> slices;
inline uint64_t read_bytes=0, read_calls=0;
inline uint32_t medium_type=0;
inline int command_priority=0;

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

inline FILE *open_readonly(const std::filesystem::path &path) {
#ifdef _WIN32
    return _wfopen(path.c_str(),L"rb");
#else
    return std::fopen(path.c_str(),"rb");
#endif
}

inline void mount(const std::filesystem::path &path,std::span<const Entry> entries,unsigned sector=2048,unsigned skip=0,unsigned medium=0) {
    std::lock_guard lock(mutex);
    if(!slices.empty())throw std::runtime_error("cannot replace a PS2 disc with open file views");
    if((sector!=2048&&sector!=2352&&sector!=2336)||skip>sector-2048)
        throw std::runtime_error("invalid PS2 disc sector layout");
    if(medium!=0&&medium!=0x12&&medium!=0x14)throw std::runtime_error("invalid PS2 disc medium type");
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
    image=path;files=std::move(next);sector_size=sector;data_skip=skip;read_bytes=read_calls=0;
    extracted_files.clear();extracted_extents.clear();extracted_sector_count=unmapped_reads=0;
    medium_type=medium?medium:(sector==2048?0x14:0x12);
}

inline void mount_directory(const std::filesystem::path &root,std::span<const Entry> entries,
                            uint64_t sector_count,unsigned medium=0x14) {
    std::lock_guard lock(mutex);
    if(!slices.empty())throw std::runtime_error("cannot replace a PS2 disc with open file views");
    if(!sector_count || sector_count>UINT32_MAX)
        throw std::runtime_error("invalid PS2 extracted disc sector count");
    if(medium!=0x12 && medium!=0x14)throw std::runtime_error("invalid PS2 disc medium type");

    std::unordered_map<std::string,Entry> next;
    std::unordered_map<std::string,std::filesystem::path> paths;
    std::vector<Extent> extents;
    for(const auto &entry:entries) {
        const auto name=normalized(entry.name);
        if(name.empty() || next.contains(name))throw std::runtime_error("invalid or duplicate PS2 disc file");
        if(entry.lba>sector_count || entry.size>(sector_count-entry.lba)*2048)
            throw std::runtime_error("PS2 extracted disc extent exceeds its logical size");

        auto path=root/name;
        std::error_code error;
        auto size=std::filesystem::file_size(path,error);
        // An ISO 9660 extension separator can disappear when the file is extracted.
        if(error && name.ends_with('.')) {
            path=root/name.substr(0,name.size()-1);
            size=std::filesystem::file_size(path,error);
        }
        if(error || size!=entry.size)
            throw std::runtime_error("missing or wrong-sized PS2 extracted disc file: "+name);
        if(entry.size)extents.push_back({path,entry.lba,entry.size});
        next.emplace(name,Entry{name,entry.lba,entry.size});
        paths.emplace(name,std::move(path));
    }
    std::sort(extents.begin(),extents.end(),[](const Extent &a,const Extent &b){return a.lba<b.lba;});
    for(size_t n=1;n<extents.size();++n) {
        if(extents[n].lba<extents[n-1].end_sector())
            throw std::runtime_error("overlapping PS2 extracted disc extents");
    }

    image.clear();files=std::move(next);extracted_files=std::move(paths);extracted_extents=std::move(extents);
    extracted_sector_count=sector_count;sector_size=2048;data_skip=0;medium_type=medium;
    read_bytes=read_calls=unmapped_reads=0;
}

inline std::filesystem::path mount_assets(const std::filesystem::path &assets,std::span<const Entry> entries,
                                          unsigned sector,unsigned skip,unsigned medium) {
    const auto directory=assets/"disc.directory";
    const auto reference_path=assets/"disc.path";
    auto image_path=assets/"disc.img";
    if(std::filesystem::exists(directory)) {
        if(std::filesystem::exists(reference_path) || std::filesystem::exists(image_path))
            throw std::runtime_error("multiple PS2 disc asset modes are present");
        if(sector!=2048 || skip!=0)
            throw std::runtime_error("PS2 extracted disc requires 2048-byte data sectors");
        if(!std::filesystem::is_regular_file(directory))
            throw std::runtime_error("invalid PS2 extracted disc marker");
        std::ifstream marker(directory);
        std::string text;
        std::getline(marker,text);
        if(text.ends_with('\r'))text.pop_back();
        uint64_t sector_count=0;
        const auto end=text.data()+text.size();
        const auto result=std::from_chars(text.data(),end,sector_count);
        if(!marker || result.ec!=std::errc{} || result.ptr!=end || marker.peek()!=EOF)
            throw std::runtime_error("invalid PS2 extracted disc marker");
        mount_directory(assets/"cd",entries,sector_count,medium?medium:0x14);
        return {};
    }

    if(std::filesystem::is_regular_file(reference_path)) {
        std::ifstream reference(reference_path);
        std::string path;
        std::getline(reference,path);
        if(path.empty() || !reference)throw std::runtime_error("invalid external disc reference");
        image_path=std::filesystem::u8path(path);
        if(!image_path.is_absolute())throw std::runtime_error("external disc reference must be absolute");
    }
    if(!std::filesystem::is_regular_file(image_path))
        throw std::runtime_error("PS2 disc assets are missing; run tools/extract_assets.py to prepare them");
    mount(image_path,entries,sector,skip,medium);
    return image_path;
}

inline uint64_t directory_sector_count() {
    std::lock_guard lock(mutex);
    return extracted_sector_count;
}

inline uint32_t medium() {std::lock_guard lock(mutex);return medium_type;}
inline bool set_priority(int value) {
    if(value<1||value>126)return false;
    std::lock_guard lock(mutex);command_priority=value;return true;
}
inline int priority() {std::lock_guard lock(mutex);return command_priority;}

inline FILE *open(const char *host,const char *mode,const char *guest) {
    if(!disc_path(guest))return std::fopen(host,mode);
    if(!mode||mode[0]!='r'||std::strchr(mode,'+')){errno=EROFS;return nullptr;}
    const auto name=normalized(guest);
    if(name.empty()){errno=ENOENT;return nullptr;}
    std::lock_guard lock(mutex);
    const auto found=files.find(name);
    if(extracted_sector_count && found!=files.end()) {
        FILE *file=open_readonly(extracted_files.at(name));
        if(file)slices.emplace(file,Slice{Entry{name,0,found->second.size}});
        return file;
    }
    // Extracted owner files may override disc assets. Code identity guards
    // still apply to executable modules independently of asset placement.
    if(FILE *local=std::fopen(host,mode))return local;
    if(found==files.end()||image.empty()){errno=ENOENT;return nullptr;}
    FILE *file=open_readonly(image);
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

inline bool mounted() {std::lock_guard lock(mutex);return !image.empty() || extracted_sector_count!=0;}

inline bool read_directory_sectors(uint32_t lba,uint8_t *destination,size_t bytes) {
    ++read_calls;
    if(!bytes)return true;

    const uint64_t start=uint64_t(lba)*2048;
    const uint64_t last_sector=(start+bytes-1)/2048;
    auto extent=std::upper_bound(extracted_extents.begin(),extracted_extents.end(),lba,
        [](uint64_t sector,const Extent &candidate){return sector<candidate.lba;});
    if(extent!=extracted_extents.begin())--extent;

    // Validate coverage before writing any guest bytes.
    uint64_t sector=lba;
    for(auto current=extent;;++current) {
        if(current==extracted_extents.end() || sector<current->lba || sector>=current->end_sector()) {
            if(++unmapped_reads<=16)
                std::fprintf(stderr,"PS2 extracted disc has no data for sector %llu\n",
                    static_cast<unsigned long long>(sector));
            errno=EIO;
            return false;
        }
        if(last_sector<current->end_sector())break;
        sector=current->end_sector();
    }

    size_t done=0;
    while(done<bytes) {
        const uint64_t position=start+done;
        const uint64_t offset=position-extent->lba*2048;
        const size_t chunk=static_cast<size_t>(std::min<uint64_t>(bytes-done,extent->end_sector()*2048-position));
        const size_t from_file=offset<extent->size
            ? static_cast<size_t>(std::min<uint64_t>(chunk,extent->size-offset)) : 0;
        if(from_file) {
            FILE *file=open_readonly(extent->path);
            if(!file)return false;
            const size_t got=physical_seek(file,static_cast<int64_t>(offset),SEEK_SET)
                ? 0 : std::fread(destination+done,1,from_file,file);
            std::fclose(file);
            if(got!=from_file)return false;
        }
        // Named extraction excludes the final sector's file alignment padding.
        if(from_file<chunk)std::memset(destination+done+from_file,0,chunk-from_file);
        done+=chunk;
        read_bytes+=chunk;
        ++extent;
    }
    return true;
}

inline bool read_sectors(uint32_t lba,uint32_t count,uint8_t *destination,size_t bytes) {
    std::lock_guard lock(mutex);
    if(bytes>uint64_t(count)*2048 || (!destination&&bytes)){errno=EINVAL;return false;}
    if(extracted_sector_count)return read_directory_sectors(lba,destination,bytes);
    if(image.empty()){errno=EINVAL;return false;}
    FILE *file=open_readonly(image);
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
