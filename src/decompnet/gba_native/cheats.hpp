#pragma once
#include "cheats/cheat_list.h"
#include "cheats/engine.h"
#include <filesystem>
#include <string>

namespace anygba { class System; }
namespace gba_frontend {
// Compiled code stays native. A device code which replaces instructions needs a
// source modification rather than the SDK's interpreter-backed ROM patch path.
std::optional<std::string> native_cheat_error(const anygba::cheats::Program& program);
class Cheats {
public:
    void load(const std::filesystem::path& persistent);
    void load_once(const std::filesystem::path& file);
    void add_once(const std::string& text);
    std::optional<std::string> commit(anygba::cheats::CheatList candidate);
    void apply(anygba::System& system, uint16_t keys, bool button);
    size_t enabled() const { return list_.active().size(); }
    const anygba::cheats::CheatList& list() const { return list_; }
    const std::filesystem::path& path() const { return path_; }
private:
    void validate() const;
    anygba::cheats::CheatList list_;
    std::filesystem::path path_;
};
#ifdef _WIN32
void show_settings(void* parent, Cheats& cheats, const std::string& customization);
#endif
}
