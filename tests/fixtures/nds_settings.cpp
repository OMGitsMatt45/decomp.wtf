// Original settings readback fixture: drawable pixels exceed logical UI size.
#include "settings.hpp"
#include "video.hpp"
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
        ds_host::Cheats cheats;
        for(unsigned i=0;i<180;++i)cheats.entries.push_back({"Entry "+std::to_string(i),{},{},false});
        const auto script=std::filesystem::path(argv[1])/"large-menu.txt";
        {std::ofstream file(script);file<<"0 enter\n1 pagedown\n2 end\n3 up\n4 enter\n5 home\n6 enter\n7 back\n8 back\n";}
        ds_host::Presentation presentation({},false);
        if(!ds_host::settings(cheats,presentation,script)||cheats.enabled_count()!=2||!cheats.entries.front().enabled||!cheats.entries.back().enabled)
            throw std::runtime_error("large catalog paging did not reach both ends");
        {
            video::Display display({"software",530,510,false,true});
            std::vector<uint32_t> top(256*192,0xffff0000),bottom(256*192,0xff00ff00);
            video::Frame frame{nullptr,top.data(),bottom.data()};
            display.set_graphics(ds_host::Scaling::Sharp,ds_host::Colors::Soft);
            display.present(frame);
            auto pixels=display.read_pixels();
            int x=0,y=0;
            if(!display.touch(265,351,x,y)||x!=128||y!=96||display.touch(130,351,x,y)||display.touch(265,159,x,y))
                throw std::runtime_error("sharp output shifted the lower-screen touch bounds");
            if(pixels[265+62*530]!=0xff000000u||pixels[265+159*530]!=0xffd21313u||top[0]!=0xffff0000u)
                throw std::runtime_error("sharp placement or soft host colors differ");
            display.set_graphics(ds_host::Scaling::Smooth,ds_host::Colors::Original);
            display.present(frame);
            pixels=display.read_pixels();
            if(pixels[265+254*530]!=top[0]||pixels[265+255*530]!=bottom[0])
                throw std::runtime_error("smooth filtering mixed the two LCDs across the hinge");
        }
        SDL_Quit();std::cout<<"Settings capture uses drawable dimensions\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
