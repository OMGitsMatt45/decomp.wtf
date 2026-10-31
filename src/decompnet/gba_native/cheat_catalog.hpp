// SPDX-License-Identifier: MIT
#pragma once
#include "cheats/codes.h"
#include <filesystem>
#include <functional>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>
namespace anygba { class System; }
namespace gba_frontend {
struct CheatPreset {
    std::string id,name,category,group,note,unavailable;
    anygba::cheats::Format format=anygba::cheats::Format::Auto;
    std::vector<std::string> code;
    anygba::cheats::Program program;
    bool project_applied=false;
};
class CheatCatalog {
public:
    void configure(std::vector<CheatPreset> presets,std::function<bool(anygba::System&)> context={},std::function<void()> changed={});
    void load(const std::filesystem::path& save);
    std::optional<std::string> set_enabled(std::string_view id,bool value,bool persist=true);
    std::optional<std::string> all_off();
    bool enabled(std::string_view id) const { return enabled_.contains(std::string(id)); }
    const std::vector<CheatPreset>& presets() const { return presets_; }
    size_t enabled_count() const { return enabled_.size(); }
    const std::string& warning() const { return warning_; }
    bool available(anygba::System& system) const { return context_&&context_(system); }
    void apply(anygba::System& system,uint16_t keys,bool button) const;
    void set_apply_filter(std::function<bool(anygba::System&,const CheatPreset&)> filter){filter_=std::move(filter);}
private:
    std::optional<std::string> save() const;
    std::vector<CheatPreset> presets_;
    std::set<std::string> enabled_;
    std::filesystem::path path_;
    std::string warning_;
    std::function<bool(anygba::System&)> context_;
    std::function<void()> changed_;
    std::function<bool(anygba::System&,const CheatPreset&)> filter_;
};
CheatCatalog& game_cheat_catalog();
}
