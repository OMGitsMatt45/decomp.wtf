#pragma once
#include <string>
namespace anygba { class System; }
// A project's optional custom/game.cpp implements this interface. It is kept
// separately from the generated baseline and compiled only when present.
namespace gba_customization {
void configure(anygba::System& system);
std::string description();
}
