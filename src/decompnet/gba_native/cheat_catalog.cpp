// SPDX-License-Identifier: MIT
#include "cheat_catalog.hpp"
#include "cheats.hpp"
#include "cheats/engine.h"
#include <algorithm>
#include <fstream>
#include <stdexcept>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace gba_frontend {
CheatCatalog& game_cheat_catalog(){static CheatCatalog catalog;return catalog;}
void CheatCatalog::configure(std::vector<CheatPreset> presets,std::function<bool(anygba::System&)> context,std::function<void()> changed){
    presets_=std::move(presets);context_=std::move(context);enabled_.clear();warning_.clear();path_.clear();
    changed_=std::move(changed);filter_={};
    std::set<std::string> ids;
    for(auto& p:presets_){
        if(p.id.empty()||p.id.size()>64||p.id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")!=p.id.npos||!ids.insert(p.id).second)
            throw std::runtime_error("invalid or duplicate built-in cheat identifier");
        if(!p.unavailable.empty()||p.code.empty())continue; // Empty code: project-owned native implementation.
        try{
            p.program=anygba::cheats::compile(p.format,p.code);
            if(auto error=native_cheat_error(p.program))p.unavailable=*error;
        }catch(const std::exception& e){p.unavailable=e.what();}
    }
}
void CheatCatalog::load(const std::filesystem::path& save_path){
    enabled_.clear();path_=save_path;warning_.clear();
    if(changed_)changed_();
    if(path_.empty())return;
    path_+=".preset-picks";
    std::ifstream in(path_,std::ios::binary);if(!in){if(std::filesystem::exists(path_))throw std::runtime_error("Cannot read preset preferences");return;}
    std::string line;if(!std::getline(in,line)||line!="decomp.wtf.preset-picks/v1")throw std::runtime_error("Unrecognized preset preference file");
    size_t count=0;
    while(std::getline(in,line)){
        if(++count>100000||line.size()>64)throw std::runtime_error("Invalid preset preference file");
        if(line.empty())continue;
        if(auto error=set_enabled(line,true,false))warning_="Some saved presets are unavailable: "+*error;
    }
    if(in.bad())throw std::runtime_error("Cannot read preset preferences");
}
std::optional<std::string> CheatCatalog::save() const{
    if(path_.empty())return "Start with a save file to remember cheat choices.";
    std::error_code ec;
    if(!path_.parent_path().empty())std::filesystem::create_directories(path_.parent_path(),ec);
    if(ec)return "Cannot create the cheat preference folder: "+ec.message();
    auto tmp=path_;tmp+=".tmp";
    {
        std::ofstream out(tmp,std::ios::binary|std::ios::trunc);
        out<<"decomp.wtf.preset-picks/v1\n";for(const auto& id:enabled_)out<<id<<'\n';
        out.close();if(!out){std::filesystem::remove(tmp,ec);return "Cannot write cheat preferences.";}
    }
#ifdef _WIN32
    if(!MoveFileExW(tmp.c_str(),path_.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){
        const auto code=GetLastError();std::filesystem::remove(tmp,ec);return "Cannot replace cheat preferences (Windows "+std::to_string(code)+").";
    }
#else
    std::filesystem::rename(tmp,path_,ec);if(ec)return "Cannot replace cheat preferences: "+ec.message();
#endif
    return {};
}
std::optional<std::string> CheatCatalog::set_enabled(std::string_view id,bool value,bool persist){
    auto it=std::find_if(presets_.begin(),presets_.end(),[&](const auto& p){return p.id==id;});
    if(it==presets_.end())return "Unknown preset: "+std::string(id);
    if(value&&!it->unavailable.empty())return it->unavailable;
    const auto old=enabled_;
    if(value){
        if(!it->group.empty())for(const auto& p:presets_)if(p.group==it->group)enabled_.erase(p.id);
        enabled_.insert(it->id);
    }else enabled_.erase(it->id);
    if(persist)if(auto error=save()){enabled_=old;return error;}
    if(changed_)changed_();
    return {};
}
std::optional<std::string> CheatCatalog::all_off(){
    const auto old=enabled_;enabled_.clear();if(auto error=save()){enabled_=old;return error;}if(changed_)changed_();return {};
}
void CheatCatalog::apply(anygba::System& system,uint16_t keys,bool button) const{
    if(enabled_.empty())return;
    for(const auto& p:presets_)if(enabled(p.id)&&!p.code.empty()&&!p.project_applied&&(!filter_||filter_(system,p)))anygba::cheats::run(p.program,system,{keys,button});
}
}
