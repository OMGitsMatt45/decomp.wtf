// Original settings readback fixture: drawable pixels exceed logical UI size.
#include "settings.hpp"
#include <stdexcept>
#include <iostream>
int main(int argc,char** argv) {
    try {
        if(argc!=2||SDL_Init(SDL_INIT_VIDEO)!=0)throw std::runtime_error("SDL setup failed");
        for(const auto size:{std::pair{1600,1040},std::pair{1100,715}}) {
            SDL_Window* window=SDL_CreateWindow("Settings fixture",0,0,size.first,size.second,SDL_WINDOW_HIDDEN);
            if(!window)throw std::runtime_error(SDL_GetError());
            SDL_Renderer* renderer=SDL_CreateRenderer(window,-1,SDL_RENDERER_SOFTWARE);
            if(!renderer||SDL_RenderSetLogicalSize(renderer,800,520)!=0)throw std::runtime_error(SDL_GetError());
            SDL_SetRenderDrawColor(renderer,25,70,120,255);SDL_RenderClear(renderer);
            const auto name=std::to_string(size.first)+"x"+std::to_string(size.second)+".png";
            if(!ds_host::capture_settings(renderer,std::filesystem::path(argv[1])/name))throw std::runtime_error("capture failed");
            SDL_DestroyRenderer(renderer);SDL_DestroyWindow(window);
        }
        SDL_Quit();std::cout<<"Settings capture uses drawable dimensions\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
