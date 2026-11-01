// SPDX-License-Identifier: CC0-1.0. Original SDL event-queue regression.
#include "keyboard.hpp"
#include <iostream>
#include <stdexcept>
void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main() {
    try {
        SDL_SetMainReady();require(SDL_Init(SDL_INIT_EVENTS)==0,SDL_GetError());
        ds_host::KeyboardFrame keyboard;
        auto queue=[](Uint32 type,SDL_Scancode code,SDL_Keycode key,bool repeat=false) {
            SDL_Event event{};event.type=type;event.key.keysym.scancode=code;
            event.key.keysym.sym=key;event.key.repeat=repeat;
            require(SDL_PushEvent(&event)==1,"queue original key event");
        };
        queue(SDL_KEYDOWN,SDL_SCANCODE_S,SDLK_s);
        queue(SDL_KEYUP,SDL_SCANCODE_S,SDLK_s);
        queue(SDL_KEYDOWN,SDL_SCANCODE_X,SDLK_x);
        queue(SDL_KEYUP,SDL_SCANCODE_X,SDLK_x);
        SDL_Event event{};
        while(SDL_PollEvent(&event))require(keyboard.event(event),"normal button cannot quit");
        dsr::InputState input;input.buttons=1u<<6;
        keyboard.apply(input);
        require(input.buttons==((1u<<10)|(1u<<6)|1u),"down/up taps survive polling and preserve scripted Up");
        input={};keyboard.apply(input);
        require(input.buttons==0,"a completed tap is consumed once");
        queue(SDL_KEYDOWN,SDL_SCANCODE_S,SDLK_s,true);
        queue(SDL_KEYDOWN,SDL_SCANCODE_F2,SDLK_F2);
        while(SDL_PollEvent(&event))require(keyboard.event(event),"unbound key cannot quit");
        keyboard.apply(input);require(input.buttons==0,"unbound keys and repeats cannot fabricate presses");
        queue(SDL_KEYDOWN,SDL_SCANCODE_RIGHT,SDLK_RIGHT);
        while(SDL_PollEvent(&event))require(keyboard.event(event),"direction down accepted");
        input={};keyboard.apply(input);require(input.buttons==(1u<<4),"press reaches this sample");
        input={};keyboard.apply(input);require(input.buttons==(1u<<4),"hold survives frames without repeats");
        queue(SDL_KEYUP,SDL_SCANCODE_RIGHT,SDLK_RIGHT);
        while(SDL_PollEvent(&event))require(keyboard.event(event),"direction release accepted");
        input={};keyboard.apply(input);require(input.buttons==0,"release reaches the very next sample");
        queue(SDL_KEYDOWN,SDL_SCANCODE_DOWN,SDLK_DOWN);
        while(SDL_PollEvent(&event))require(keyboard.event(event),"second direction accepted");
        input={};keyboard.apply(input);require(input.buttons==(1u<<7),"second hold starts immediately");
        SDL_Event focus{};focus.type=SDL_WINDOWEVENT;focus.window.event=SDL_WINDOWEVENT_FOCUS_LOST;
        require(SDL_PushEvent(&focus)==1,"queue focus loss");
        while(SDL_PollEvent(&event))require(keyboard.event(event),"focus event accepted");
        input={};keyboard.apply(input);require(input.buttons==0,"focus loss cannot leave movement held");
        queue(SDL_KEYDOWN,SDL_SCANCODE_ESCAPE,SDLK_ESCAPE);
        queue(SDL_KEYUP,SDL_SCANCODE_ESCAPE,SDLK_ESCAPE);
        bool running=true;while(SDL_PollEvent(&event))running=keyboard.event(event)&&running;
        require(!running,"quick Escape tap exits without waiting for held state");
        SDL_Quit();std::cout<<"SDL keyboard queue checks passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
