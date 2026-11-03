#pragma once
#include "cheats.hpp"
#include "presentation.hpp"
#include "dsr/runtime/frontend/src/ui_toolkit.h"
#include <map>
#include <memory>

namespace ds_host {
inline bool capture_settings(SDL_Renderer* renderer,const std::filesystem::path& path) {
    int width=0,height=0;
    if(SDL_GetRendererOutputSize(renderer,&width,&height)!=0)return false;
    return dsr::ui_detail::save_renderer_png(renderer,path,width,height);
}
// The game pauses while this built-in settings window owns input.
inline bool settings(Cheats& cheats,Presentation& presentation,const std::filesystem::path& script={},const std::filesystem::path& capture={}) {
    using namespace dsr::ui_detail;
    std::map<unsigned,SDL_Keycode> inputs;
    if(!script.empty()) {
        std::ifstream file(script);if(!file)throw std::runtime_error("could not read settings input script");
        unsigned frame;std::string key;
        while(file>>frame>>key) {
            SDL_Keycode code=key=="up"?SDLK_UP:key=="down"?SDLK_DOWN:key=="enter"?SDLK_RETURN:key=="back"?SDLK_ESCAPE:
                key=="left"?SDLK_LEFT:key=="right"?SDLK_RIGHT:
                key=="pageup"?SDLK_PAGEUP:key=="pagedown"?SDLK_PAGEDOWN:key=="home"?SDLK_HOME:key=="end"?SDLK_END:0;
            if(!code||frame>10000)throw std::runtime_error("invalid settings input script");
            inputs[frame]=code;
        }
        if(!file.eof())throw std::runtime_error("malformed settings input script");
    }
    using Window=std::unique_ptr<SDL_Window,decltype(&SDL_DestroyWindow)>;
    using Renderer=std::unique_ptr<SDL_Renderer,decltype(&SDL_DestroyRenderer)>;
    Window window(SDL_CreateWindow("Game settings",SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED,800,520,SDL_WINDOW_SHOWN),SDL_DestroyWindow);
    if(!window)throw std::runtime_error(SDL_GetError());
    Renderer renderer(SDL_CreateRenderer(window.get(),-1,SDL_RENDERER_SOFTWARE),SDL_DestroyRenderer);
    if(!renderer)throw std::runtime_error(SDL_GetError());
    if(SDL_RenderSetLogicalSize(renderer.get(),800,520)!=0)throw std::runtime_error(SDL_GetError());
    UiCanvas canvas(renderer.get());
    constexpr int root=0,cheat_page=1,back=-1,resume=-2,cheat=-3;
    int page=root;
    bool done=false,running=true;size_t selected=0;
    const std::vector<Presentation::Entry> root_rows{{"Cheats",cheat},{"Audio",Presentation::audio_page},
                                                    {"Graphics",Presentation::graphics_page},{"Resume game",resume}};
    auto count_rows=[&]() {
        if(page==root)return root_rows.size();
        if(page==cheat_page)return cheats.entries.size()+1;
        return presentation.rows(page,back).size();
    };
    auto go_back=[&]() {if(page==root)done=true;else page=root;selected=0;};
    auto key=[&](SDL_Keycode code) {
        const size_t count=count_rows();
        if(code==SDLK_UP)selected=(selected+count-1)%count;
        else if(code==SDLK_DOWN)selected=(selected+1)%count;
        else if(code==SDLK_PAGEUP)selected=selected>9?selected-9:0;
        else if(code==SDLK_PAGEDOWN)selected=std::min(selected+9,count-1);
        else if(code==SDLK_HOME)selected=0;
        else if(code==SDLK_END)selected=count-1;
        else if(code==SDLK_ESCAPE||code==SDLK_F1)go_back();
        else if(Presentation::is_page(page)&&(code==SDLK_LEFT||code==SDLK_RIGHT))
            presentation.change(presentation.rows(page,back)[selected].action,code==SDLK_LEFT?-1:1);
        else if(code==SDLK_RETURN||code==SDLK_SPACE) {
            if(page==root) {
                const int action=root_rows[selected].action;
                if(action==resume)done=true;
                else {page=action==cheat?cheat_page:action;selected=0;presentation.status.clear();}
            } else if(page==cheat_page) {
                if(selected==cheats.entries.size())go_back();else cheats.toggle(selected);
            } else if(!presentation.change(presentation.rows(page,back)[selected].action))go_back();
        }
    };
    ++cheats.menu_openings;
    for(unsigned frame=0;!done;++frame) {
        if(!script.empty()&&frame>10000)throw std::runtime_error("settings input script did not close the menu");
        SDL_Event event;
        while(SDL_PollEvent(&event)) {
            if(event.type==SDL_QUIT){running=false;done=true;}
            else if(event.type==SDL_WINDOWEVENT&&event.window.event==SDL_WINDOWEVENT_CLOSE) {
                if(event.window.windowID==SDL_GetWindowID(window.get()))done=true;
                else{running=false;done=true;}
            } else if(event.type==SDL_KEYDOWN&&!event.key.repeat&&event.key.windowID==SDL_GetWindowID(window.get()))key(event.key.keysym.sym);
            else if(event.type==SDL_MOUSEBUTTONDOWN&&event.button.windowID==SDL_GetWindowID(window.get())) {
                const size_t first=page&&selected>8?selected-8:0;
                const int row=(event.button.y-104)/34;
                const size_t count=count_rows();
                if(event.button.x>=24&&event.button.x<776&&event.button.y>=104&&row<9&&first+size_t(row)<count){selected=first+size_t(row);key(SDLK_RETURN);}
            }
        }
        if(const auto found=inputs.find(frame);found!=inputs.end())key(found->second);
        canvas.clear({19,25,39,255});
        const char* title=page==root?"Game settings":page==cheat_page?"Settings / Cheats":
                          page==Presentation::audio_page?"Settings / Audio":"Settings / Graphics";
        canvas.text(24,22,title,{241,245,255,255},3);
        if(page==cheat_page)canvas.text(600,32,std::to_string(selected+1)+"/"+std::to_string(cheats.entries.size()+1),{175,190,215,255},2);
        canvas.text(24,68,"Arrows/PgUp/PgDn: select   Enter: change   Esc: back",{175,190,215,255},2);
        const size_t count=count_rows();
        const size_t first=page&&selected>8?selected-8:0;
        for(size_t row=0;row<9&&first+row<count;++row) {
            const auto index=first+row;
            const std::string label=page==root?root_rows[index].name:Presentation::is_page(page)?presentation.rows(page,back)[index].name:
                index==cheats.entries.size()?"Back":std::string(cheats.entries[index].enabled?"[ON]  ":"[OFF] ")+cheats.entries[index].name;
            canvas.button({24,104+int(row)*34,752,30},label,index==selected);
        }
        if(Presentation::is_page(page)) {
            canvas.text(24,442,"Left/Right or Enter: change. Takes effect on resume.",{175,190,215,255},2);
            canvas.text(24,472,presentation.status,{233,223,168,255},2);
        } else {
            canvas.text(24,442,"Cheats start OFF each launch. Gameplay is paused.",{175,190,215,255},2);
            canvas.text(24,472,"Granted items/stats remain when a cheat is turned off.",{175,190,215,255},2);
        }
        if(!capture.empty()&&frame==0&&!capture_settings(renderer.get(),capture))throw std::runtime_error("could not capture settings");
        SDL_RenderPresent(renderer.get());++cheats.menu_frames;
        SDL_Delay(16);
    }
    // Consume key releases before the game regains its controls.
    if(script.empty()&&running) {
        for(;;) {
            SDL_PumpEvents();const auto* state=SDL_GetKeyboardState(nullptr);
            if(!state[SDL_SCANCODE_RETURN]&&!state[SDL_SCANCODE_SPACE]&&!state[SDL_SCANCODE_UP]&&!state[SDL_SCANCODE_DOWN]&&!state[SDL_SCANCODE_ESCAPE])break;
            SDL_Delay(8);
        }
    }
    return running;
}
}
