// SPDX-License-Identifier: MIT
#pragma once
#include "cheat_catalog.hpp"
#include <cstdint>
#include <span>
#include <map>
#include <vector>
namespace gba_video { class Display; }
namespace gba_frontend {
class Cheats;
class CheatBrowser {
public:
    bool show(gba_video::Display& display,CheatCatalog& catalog,Cheats& custom,const std::string& status);
    void present_hint(gba_video::Display& display,std::span<const uint16_t> game);
    uint16_t held_on_close() const {return held_;}
    void set_input_script(std::map<uint64_t,uint16_t> script){script_=std::move(script);}
    uint64_t openings() const {return openings_;}
    uint64_t presented_frames() const {return presented_frames_;}
private:
    size_t category_=0,selection_=0;
    uint16_t held_=0;
    std::vector<uint16_t> pixels_;
    std::map<uint64_t,uint16_t> script_;
    uint64_t openings_=0,presented_frames_=0;
};
}
