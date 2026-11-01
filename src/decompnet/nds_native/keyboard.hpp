// SPDX-License-Identifier: MIT
#pragma once
#include <SDL.h>
#include <dsr/machine.h>
#include <array>

namespace ds_host {
class KeyboardFrame {
    inline static constexpr std::array<SDL_Scancode,12> codes{
        SDL_SCANCODE_X,SDL_SCANCODE_Z,SDL_SCANCODE_BACKSPACE,SDL_SCANCODE_RETURN,
        SDL_SCANCODE_RIGHT,SDL_SCANCODE_LEFT,SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,
        SDL_SCANCODE_W,SDL_SCANCODE_Q,SDL_SCANCODE_S,SDL_SCANCODE_A};
    uint16_t presses=0,held=0;
public:
    bool event(const SDL_Event& event) {
        if(event.type==SDL_WINDOWEVENT&&event.window.event==SDL_WINDOWEVENT_FOCUS_LOST) {
            presses=held=0;
            return true;
        }
        if(event.type!=SDL_KEYDOWN&&event.type!=SDL_KEYUP)return true;
        if(event.type==SDL_KEYDOWN&&event.key.keysym.sym==SDLK_ESCAPE)return false;
        for(unsigned i=0;i<codes.size();++i)if(event.key.keysym.scancode==codes[i]) {
            const auto bit=uint16_t(1u<<i);
            if(event.type==SDL_KEYUP)held&=uint16_t(~bit);
            else if(!event.key.repeat){held|=bit;presses|=bit;}
        }
        return true;
    }
    void apply(dsr::InputState& input) {
        // Use the ordered transitions just polled, including releases. A quick
        // down/up still survives one sample; holds last only until key-up.
        input.buttons|=held|presses;
        presses=0;
    }
};
}
