// SPDX-License-Identifier: MIT
#pragma once
#include "decomp_cheats.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>

namespace decomp_ps2_settings {
inline std::string lower(std::string value){for(auto &c:value)c=char(std::tolower(static_cast<unsigned char>(c)));return value;}
inline bool open(SDL_Window *game,const std::filesystem::path &script={},const std::filesystem::path &capture={}){
    auto *window=SDL_CreateWindow("Game settings",1000,650,SDL_WINDOW_RESIZABLE);
    if(!window)throw std::runtime_error(SDL_GetError());
    auto *renderer=SDL_CreateRenderer(window,"software");
    if(!renderer){SDL_DestroyWindow(window);throw std::runtime_error(SDL_GetError());}
    struct Cleanup{SDL_Window*w;SDL_Renderer*r;~Cleanup(){SDL_StopTextInput(w);SDL_DestroyRenderer(r);SDL_DestroyWindow(w);}}cleanup{window,renderer};
    SDL_SetRenderLogicalPresentation(renderer,1000,650,SDL_LOGICAL_PRESENTATION_LETTERBOX);
    SDL_StartTextInput(window);
    std::map<unsigned,std::string> inputs;
    if(!script.empty()){
        std::ifstream file(script);if(!file)throw std::runtime_error("cannot open settings script");
        unsigned frame;std::string key;
        while(file>>frame>>key){if(frame>10000)throw std::runtime_error("settings script frame bound");inputs[frame]=key;}
        if(!file.eof())throw std::runtime_error("malformed settings script");
    }
    bool cheats=false,done=false,running=true;size_t selected=0,category=0;std::string search;
    std::vector<std::string> categories={"All cheats"};
    for(const auto &e:decomp_ps2_cheats::entries)if(std::find(categories.begin(),categories.end(),e.group)==categories.end())categories.push_back(e.group);
    std::vector<size_t> visible;
    auto refresh=[&]{
        visible.clear();
        for(size_t n=0;n<decomp_ps2_cheats::entries.size();++n){const auto &e=decomp_ps2_cheats::entries[n];
            if((!category||e.group==categories[category])&&(search.empty()||lower(e.name).find(lower(search))!=std::string::npos))visible.push_back(n);
        }
        selected=visible.empty()?0:std::min(selected,visible.size()-1);
    };
    refresh();
    auto action=[&](const std::string &key){
        const size_t count=cheats?visible.size():3;
        if(key=="back"||key=="f1"){if(cheats){cheats=false;selected=0;search.clear();refresh();}else done=true;}
        else if(key=="up"&&count)selected=(selected+count-1)%count;
        else if(key=="down"&&count)selected=(selected+1)%count;
        else if(key=="pageup")selected=selected>11?selected-11:0;
        else if(key=="pagedown"&&count)selected=std::min(selected+11,count-1);
        else if(key=="home")selected=0;
        else if(key=="end"&&count)selected=count-1;
        else if((key=="left"||key=="right")&&cheats){category=(category+categories.size()+(key=="right"?1:-1))%categories.size();selected=0;refresh();}
        else if(key=="enter"){
            if(cheats){if(!visible.empty())decomp_ps2_cheats::toggle(visible[selected]);}
            else if(selected==0){cheats=true;selected=0;refresh();}
            else if(selected==1)SDL_SetWindowFullscreen(game,!(SDL_GetWindowFlags(game)&SDL_WINDOW_FULLSCREEN));
            else done=true;
        }else if(key.starts_with("search:")){search=key.substr(7);selected=0;refresh();}
    };
    ++decomp_ps2_cheats::menu_openings;
    for(unsigned frame=0;!done;++frame){
        if(!script.empty()&&frame>10000)throw std::runtime_error("settings script did not close the menu");
        SDL_Event event;
        while(SDL_PollEvent(&event)){
            if(event.type==SDL_EVENT_QUIT){done=true;running=false;}
            else if(event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED){done=true;if(event.window.windowID!=SDL_GetWindowID(window))running=false;}
            else if(event.type==SDL_EVENT_KEY_DOWN&&event.key.windowID==SDL_GetWindowID(window)&&!event.key.repeat){
                const auto scan=event.key.scancode;
                const char *key=scan==SDL_SCANCODE_UP?"up":scan==SDL_SCANCODE_DOWN?"down":scan==SDL_SCANCODE_RETURN?"enter":scan==SDL_SCANCODE_ESCAPE?"back":scan==SDL_SCANCODE_F1?"f1":scan==SDL_SCANCODE_PAGEUP?"pageup":scan==SDL_SCANCODE_PAGEDOWN?"pagedown":scan==SDL_SCANCODE_HOME?"home":scan==SDL_SCANCODE_END?"end":scan==SDL_SCANCODE_LEFT?"left":scan==SDL_SCANCODE_RIGHT?"right":"";
                if(*key)action(key);
                else if(scan==SDL_SCANCODE_BACKSPACE&&cheats&&!search.empty()){search.pop_back();selected=0;refresh();}
            }else if(event.type==SDL_EVENT_TEXT_INPUT&&event.text.windowID==SDL_GetWindowID(window)&&cheats){
                if(search.size()<100){search+=event.text.text;selected=0;refresh();}
            }else if(event.type==SDL_EVENT_MOUSE_WHEEL&&event.wheel.windowID==SDL_GetWindowID(window))action(event.wheel.y>0?"up":"down");
        }
        if(const auto it=inputs.find(frame);it!=inputs.end())action(it->second);
        SDL_SetRenderDrawColor(renderer,19,25,39,255);SDL_RenderClear(renderer);
        auto text=[&](float x,float y,const std::string &value,bool bright=true){
            SDL_SetRenderScale(renderer,2,2);SDL_SetRenderDrawColor(renderer,bright?242:165,bright?246:185,bright?255:210,255);
            SDL_RenderDebugText(renderer,x/2,y/2,value.c_str());SDL_SetRenderScale(renderer,1,1);
        };
        text(24,24,cheats?"Settings / Cheats":"Game settings");
        text(24,58,"Arrows: select  Enter: toggle  PgUp/Dn: scroll  Esc: back",false);
        if(cheats){text(24,88,"Category: "+categories[category]+"  (Left/Right)",false);text(24,114,"Search: "+search+"_",false);}
        const size_t count=cheats?visible.size():3;const size_t first=selected>10?selected-10:0;
        for(size_t row=0;row<11&&first+row<count;++row){
            const size_t n=first+row;const float y=154+float(row)*34;
            if(n==selected){SDL_SetRenderDrawColor(renderer,42,65,100,255);SDL_FRect box{20,y-5,960,30};SDL_RenderFillRect(renderer,&box);}
            std::string label;
            if(!cheats)label=n==0?"Cheats":n==1?"Toggle fullscreen":"Resume game";
            else{const auto &e=decomp_ps2_cheats::entries[visible[n]];label=std::string(e.enabled?"[ON]  ":"[OFF] ")+e.name;}
            if(label.size()>58)label=label.substr(0,55)+"...";
            text(30,y,label);
        }
        if(cheats&&!visible.empty()){const auto &e=decomp_ps2_cheats::entries[visible[selected]];text(24,548,e.group+"  |  "+std::to_string(selected+1)+" / "+std::to_string(visible.size()),false);}
        text(24,582,"Cheats start OFF. Conflicting choices replace each other.",false);
        text(24,610,"Granted items/stats remain after disabling a cheat.",false);
        if(!capture.empty()&&frame==8){
            auto *surface=SDL_RenderReadPixels(renderer,nullptr);
            if(!surface)throw std::runtime_error(SDL_GetError());
            const bool saved=SDL_SaveBMP(surface,capture.string().c_str());SDL_DestroySurface(surface);
            if(!saved)throw std::runtime_error(SDL_GetError());
        }
        SDL_RenderPresent(renderer);SDL_Delay(16);
    }
    return running;
}
}
