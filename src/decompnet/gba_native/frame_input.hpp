// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <utility>

namespace gba_frontend {
struct FrameInput {
    std::uint16_t keys=0;
    bool settings=false,cheat_button=false,running=true;
};
// Rendering and frame pacing can take a whole display interval. Latch live
// controls afterwards, immediately before the next emulated frame consumes them.
template<class Display,class Present>
FrameInput present_and_sample(Display& display,Present&& present,bool paced) {
    std::forward<Present>(present)();
    if(paced)display.pace();
    FrameInput input;
    input.running=display.poll(input.keys,&input.settings,&input.cheat_button);
    return input;
}
}
