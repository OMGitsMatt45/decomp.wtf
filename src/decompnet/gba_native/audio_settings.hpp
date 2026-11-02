// SPDX-License-Identifier: MIT
#pragma once
#include <filesystem>
#include <fstream>
#include <functional>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace gba_frontend {
class AudioSettings {
public:
    bool enhanced=false;
    std::function<void(bool)> changed;
    void load(const std::filesystem::path& save,bool default_mode) {
        enhanced=default_mode;path_=save;
        if(path_.empty())return;
        path_+=".audio.cfg";
        std::error_code error;
        if(!std::filesystem::exists(path_,error)) {
            if(error)throw std::runtime_error("cannot inspect audio settings");
            return;
        }
        std::ifstream file(path_);std::string line;
        if(!std::getline(file,line) || (line!="enhanced=0" && line!="enhanced=1"))
            throw std::runtime_error("invalid audio settings: "+path_.string());
        enhanced=line=="enhanced=1";
    }
    void set(bool value,bool persist=false) {
        if(persist && !path_.empty()) {
            if(!path_.parent_path().empty())std::filesystem::create_directories(path_.parent_path());
            auto temporary=path_;temporary+=".tmp";
            {std::ofstream file(temporary,std::ios::trunc);file<<"enhanced="<<(value?1:0)<<'\n';
                file.close();if(!file)throw std::runtime_error("cannot write audio settings");}
#ifdef _WIN32
            if(!MoveFileExW(temporary.c_str(),path_.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
                throw std::runtime_error("cannot replace audio settings");
#else
            std::filesystem::rename(temporary,path_);
#endif
        }
        enhanced=value;if(changed)changed(value);
    }
private:
    std::filesystem::path path_;
};
}
