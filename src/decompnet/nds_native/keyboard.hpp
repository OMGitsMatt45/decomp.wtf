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
    uint16_t presses=0;
public:
    bool event(const SDL_Event& event) {
        if(event.type!=SDL_KEYDOWN||event.key.repeat)return true;
        if(event.key.keysym.sym==SDLK_ESCAPE)return false;
        for(unsigned i=0;i<codes.size();++i)
            if(event.key.keysym.scancode==codes[i])presses|=uint16_t(1u<<i);
        return true;
    }
    void apply(dsr::InputState& input) {
        // A down/up pair already in the queue must survive final-state polling.
        // Retain normal holds and merge, rather than replace, scripted input.
        const auto* held=SDL_GetKeyboardState(nullptr);
        input.buttons|=presses;
        for(unsigned i=0;i<codes.size();++i)if(held[codes[i]])input.buttons|=uint16_t(1u<<i);
        presses=0;
    }
};
}
