#include "cheats.hpp"
#include <stdexcept>

namespace gba_frontend {
std::optional<std::string> native_cheat_error(const anygba::cheats::Program& program) {
    if (program.has_rom_patch)
        return "This code changes cartridge instructions or literals. It requires a native source patch; live ROM patches are unavailable in this player.";
    return {};
}
void Cheats::validate() const {
    if(!list_.warnings().empty())throw std::runtime_error(list_.warnings().back());
    for (const auto* program:list_.active())
        if (auto error=native_cheat_error(*program)) throw std::runtime_error(*error);
}
void Cheats::load(const std::filesystem::path& path) {
    path_=path;
    if(!path.empty())list_.load_user(path);
    validate();
}
void Cheats::load_once(const std::filesystem::path& path) {
    if(!std::filesystem::is_regular_file(path))throw std::runtime_error("Cannot open cheat file: "+path.string());
    list_.load_user(path,false);
    validate();
}
void Cheats::add_once(const std::string& text) {
    auto format=anygba::cheats::Format::Auto;
    std::string body=text;
    if(auto colon=text.find(':');colon!=text.npos)
        if(auto parsed=anygba::cheats::parse_format(std::string_view(text).substr(0,colon))) {
            format=*parsed;body=text.substr(colon+1);
        }
    auto index=list_.add_custom("Command line code",format,anygba::cheats::split_lines(body),false);
    if(auto error=list_.set_enabled(index,true))throw std::runtime_error(*error);
    validate();
}
std::optional<std::string> Cheats::commit(anygba::cheats::CheatList candidate) {
    for(const auto* program:candidate.active())if(auto error=native_cheat_error(*program))return error;
    if(path_.empty())return "No settings destination is available. Start the player with a save path.";
    if(auto error=candidate.save_user(path_,"Native GBA game"))return error;
    list_=std::move(candidate);
    return {};
}
void Cheats::apply(anygba::System& system,uint16_t keys,bool button) {
    for(const auto* program:list_.active())anygba::cheats::run(*program,system,{keys,button});
}
}
