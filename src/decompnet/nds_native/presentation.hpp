// SPDX-License-Identifier: MIT. Host preferences for a native DS project.
#pragma once
#include <dsr/spu.h>
#include <filesystem>
#include <fstream>
#include <ostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace ds_host {
enum class Scaling { Original, Sharp, Smooth };
enum class Colors { Original, Soft };

inline const char* name(Scaling value) {
    switch(value) {
    case Scaling::Sharp: return "sharp";
    case Scaling::Smooth: return "smooth";
    default: return "original";
    }
}
inline const char* name(Colors value) { return value==Colors::Soft?"soft":"original"; }
inline Scaling parse_scaling(std::string_view value) {
    if(value=="original")return Scaling::Original;
    if(value=="sharp")return Scaling::Sharp;
    if(value=="smooth")return Scaling::Smooth;
    throw std::runtime_error("scaling must be original, sharp or smooth");
}
inline Colors parse_colors(std::string_view value) {
    if(value=="original")return Colors::Original;
    if(value=="soft")return Colors::Soft;
    throw std::runtime_error("colors must be original or soft");
}

class Presentation {
public:
    static constexpr int audio_page=-100, graphics_page=-101;
    struct Entry { std::string name; int action; };

    Presentation(const std::filesystem::path& save,bool desktop):enhanced_audio(desktop) {
        if(!desktop||save.empty())return;
        audio_path_=graphics_path_=std::filesystem::weakly_canonical(save);
        audio_path_+=".audio.cfg";
        graphics_path_+=".graphics.cfg";
        std::ifstream audio(audio_path_);
        std::string line;
        if(std::getline(audio,line)) {
            if(line=="enhanced=0")enhanced_audio=false;
            if(line=="enhanced=1")enhanced_audio=true;
        }
        std::ifstream graphics(graphics_path_);
        while(std::getline(graphics,line)) {
            if(line=="scaling=original")scaling=Scaling::Original;
            else if(line=="scaling=sharp")scaling=Scaling::Sharp;
            else if(line=="scaling=smooth")scaling=Scaling::Smooth;
            else if(line=="colors=original")colors=Colors::Original;
            else if(line=="colors=soft")colors=Colors::Soft;
        }
    }

    bool enhanced_audio=false;
    Scaling scaling=Scaling::Original;
    Colors colors=Colors::Original;
    bool fullscreen=false;
    std::string status;

    void override_audio(std::string_view value) {
        if(value=="original")enhanced_audio=false;
        else if(value=="enhanced")enhanced_audio=true;
        else throw std::runtime_error("audio mode must be original or enhanced");
    }
    void apply_audio(dsr::Spu& spu) const {
        spu.set_output_quality(enhanced_audio?dsr::Spu::OutputQuality::Clean:dsr::Spu::OutputQuality::Hardware);
    }
    void report(std::ostream& out) const {
        out<<",\"presentation\":{\"audio\":\""<<(enhanced_audio?"enhanced":"original")
           <<"\",\"scaling\":\""<<name(scaling)<<"\",\"colors\":\""<<name(colors)
           <<"\",\"fullscreen\":"<<(fullscreen?"true":"false")<<"}";
    }

    static bool is_page(int page) { return page==audio_page||page==graphics_page; }
    std::vector<Entry> rows(int page,int back) const {
        if(page==audio_page)return {{enhanced_audio?"Audio: Enhanced":"Audio: Original",change_audio},{"Back",back}};
        const char* scale=scaling==Scaling::Sharp?"Sharp":scaling==Scaling::Smooth?"Smooth":"Original";
        return {{std::string("Scaling: ")+scale,change_scaling},
                {colors==Colors::Soft?"Colors: Soft":"Colors: Original",change_colors},
                {fullscreen?"Fullscreen: On":"Fullscreen: Off",change_fullscreen},{"Back",back}};
    }
    bool change(int action,int direction=1) {
        if(action<change_fullscreen||action>change_audio)return false;
        status.clear();
        try {
            if(action==change_audio) {
                write(audio_path_,enhanced_audio?"enhanced=0\n":"enhanced=1\n");
                enhanced_audio=!enhanced_audio;
            } else if(action==change_fullscreen) {
                fullscreen=!fullscreen;
            } else {
                const auto scale=action==change_scaling?static_cast<Scaling>((int(scaling)+direction+3)%3):scaling;
                const auto color=action==change_colors?(colors==Colors::Soft?Colors::Original:Colors::Soft):colors;
                write(graphics_path_,std::string("scaling=")+name(scale)+"\ncolors="+name(color)+"\n");
                scaling=scale;
                colors=color;
            }
        } catch(const std::exception&) {
            status="Could not save this preference.";
        }
        return true;
    }
private:
    static constexpr int change_audio=-102, change_scaling=-103, change_colors=-104, change_fullscreen=-105;
    std::filesystem::path audio_path_,graphics_path_;

    // The cartridge save lock also serializes writers to its preference files.
    static void write(const std::filesystem::path& path,std::string_view value) {
        if(path.empty())return;
        auto temporary=path;
        temporary+=".tmp";
        {
            std::ofstream out(temporary,std::ios::trunc);
            out<<value;
            out.close();
            if(!out)throw std::runtime_error("could not write presentation preferences");
        }
#ifdef _WIN32
        if(!MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
            throw std::runtime_error("could not replace presentation preferences");
#else
        std::filesystem::rename(temporary,path);
#endif
    }
};
}
