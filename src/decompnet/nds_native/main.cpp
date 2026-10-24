// SPDX-License-Identifier: MIT. Original decomp.wtf generated-project host.
#include <dsr/session.h>
#include <dsr/rt.h>
#include <dsr/gpu2d.h>
#include <dsr/periph.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef NDS_WITH_SDL
#include <SDL.h>
#endif
#include "profile.hpp"

namespace {
uint64_t count(const std::string& text,uint64_t maximum) {
    if(text.empty() || text.find_first_not_of("0123456789")!=std::string::npos)
        throw std::runtime_error("expected a positive number");
    const auto value=std::stoull(text);
    if(!value || value>maximum)throw std::runtime_error("number outside supported range");
    return value;
}
uint64_t hash(const uint32_t* pixels) {
    uint64_t value=0xcbf29ce484222325ull;
    for(unsigned i=0;i<256*192;++i)for(unsigned shift:{0u,8u,16u}) {
        value^=(pixels[i]>>shift)&255u;value*=0x100000001b3ull;
    }
    return value;
}
void ppm(const std::filesystem::path& path,const uint32_t* pixels) {
    std::ofstream output(path,std::ios::binary);
    output<<"P6\n256 192\n255\n";
    for(unsigned i=0;i<256*192;++i)for(unsigned shift:{16u,8u,0u})output.put(char(pixels[i]>>shift));
    if(!output)throw std::runtime_error("could not write screen capture");
}
#ifdef NDS_WITH_SDL
struct Display {
    SDL_Window* window=nullptr;
    SDL_Renderer* renderer=nullptr;
    SDL_Texture* texture=nullptr;
    SDL_AudioDeviceID audio=0;
    SDL_AudioStream* resampler=nullptr;
    Display() {
        if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_AUDIO|SDL_INIT_EVENTS)!=0)throw std::runtime_error(SDL_GetError());
        window=SDL_CreateWindow("DS PC project",SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED,
                                512,768,SDL_WINDOW_RESIZABLE);
        if(window)renderer=SDL_CreateRenderer(window,-1,SDL_RENDERER_ACCELERATED|SDL_RENDERER_PRESENTVSYNC);
        if(window && !renderer)renderer=SDL_CreateRenderer(window,-1,SDL_RENDERER_SOFTWARE);
        if(renderer)texture=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STREAMING,256,384);
        if(!texture)throw std::runtime_error(SDL_GetError());
        SDL_RenderSetLogicalSize(renderer,256,384);
        SDL_AudioSpec wanted{};wanted.freq=48000;wanted.format=AUDIO_S16SYS;wanted.channels=2;wanted.samples=1024;
        audio=SDL_OpenAudioDevice(nullptr,0,&wanted,nullptr,0);
        if(!audio)throw std::runtime_error(SDL_GetError());
        resampler=SDL_NewAudioStream(AUDIO_S16SYS,2,int(dsr::Session::audio_rate()+0.5),AUDIO_S16SYS,2,wanted.freq);
        if(!resampler)throw std::runtime_error(SDL_GetError());
        SDL_PauseAudioDevice(audio,0);
    }
    ~Display() {
        if(audio)SDL_CloseAudioDevice(audio);
        if(resampler)SDL_FreeAudioStream(resampler);
        if(texture)SDL_DestroyTexture(texture);
        if(renderer)SDL_DestroyRenderer(renderer);
        if(window)SDL_DestroyWindow(window);
        SDL_Quit();
    }
    bool input(dsr::InputState& input) {
        SDL_Event event;
        while(SDL_PollEvent(&event))if(event.type==SDL_QUIT)return false;
        const auto* keys=SDL_GetKeyboardState(nullptr);
        const SDL_Scancode codes[]={SDL_SCANCODE_X,SDL_SCANCODE_Z,SDL_SCANCODE_BACKSPACE,SDL_SCANCODE_RETURN,
            SDL_SCANCODE_RIGHT,SDL_SCANCODE_LEFT,SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,
            SDL_SCANCODE_W,SDL_SCANCODE_Q,SDL_SCANCODE_S,SDL_SCANCODE_A};
        for(unsigned i=0;i<12;++i)if(keys[codes[i]])input.buttons|=1u<<i;
        if(keys[SDL_SCANCODE_ESCAPE])return false;
        int x,y;const auto buttons=SDL_GetMouseState(&x,&y);
        float logical_x,logical_y;
        SDL_RenderWindowToLogical(renderer,x,y,&logical_x,&logical_y);
        input.pen_down=(buttons&SDL_BUTTON_LMASK) && logical_x>=0 && logical_x<256 && logical_y>=192 && logical_y<384;
        input.pen_x=int(logical_x);input.pen_y=int(logical_y)-192;
        return true;
    }
    void present(dsr::Session& session) {
        SDL_Rect top{0,0,256,192},bottom{0,192,256,192};
        SDL_UpdateTexture(texture,&top,session.screen_top(),256*4);
        SDL_UpdateTexture(texture,&bottom,session.screen_bottom(),256*4);
        SDL_RenderClear(renderer);SDL_RenderCopy(renderer,texture,nullptr,nullptr);SDL_RenderPresent(renderer);
        if(SDL_AudioStreamPut(resampler,session.audio_data(),int(session.audio_frames()*4))!=0)
            throw std::runtime_error(SDL_GetError());
        const int available=SDL_AudioStreamAvailable(resampler);
        if(available<0)throw std::runtime_error(SDL_GetError());
        if(available) {
            std::vector<uint8_t> bytes(size_t(available),uint8_t(0));
            const int got=SDL_AudioStreamGet(resampler,bytes.data(),available);
            if(got<0)throw std::runtime_error(SDL_GetError());
            if(SDL_GetQueuedAudioSize(audio)>48000*4/2)SDL_ClearQueuedAudio(audio);
            if(SDL_QueueAudio(audio,bytes.data(),uint32_t(got))!=0)throw std::runtime_error(SDL_GetError());
        }
    }
};
#endif
}

int main(int argc,char** argv) {
    try {
        std::filesystem::path assets="assets",save="saves/game.sav",capture,script,audio_path,memory_dump;
        uint64_t frames=0;bool headless=false,diagnostics=false;
        for(int i=1;i<argc;++i) {
            const std::string option=argv[i];
            if(option=="--headless"){headless=true;continue;}
            if(option=="--diagnostics"){diagnostics=true;continue;}
            if(i+1>=argc)throw std::runtime_error("missing option value");
            const std::string value=argv[++i];
            if(option=="--assets")assets=value;
            else if(option=="--save")save=value;
            else if(option=="--frames")frames=count(value,1000000);
            else if(option=="--capture")capture=value;
            else if(option=="--input-script")script=value;
            else if(option=="--audio-pcm")audio_path=value;
            else if(option=="--dump-memory")memory_dump=value;
            else throw std::runtime_error("unknown option: "+option);
        }
        if(headless && !frames)throw std::runtime_error("headless mode requires --frames N");
#ifndef NDS_WITH_SDL
        if(!headless)throw std::runtime_error("rebuild with NDS_WITH_SDL=ON for a window");
#endif
        if(!save.parent_path().empty())std::filesystem::create_directories(save.parent_path());
        dsr::MachineConfig config;
        config.rom_path=assets/"game.nds";config.save_path=save;
        config.arm9_table=dsr::gen_table_arm9();config.arm7_table=dsr::gen_table_arm7();
        config.arm9_regions=dsr::gen_dispatch_regions_arm9();config.arm7_regions=dsr::gen_dispatch_regions_arm7();
        config.guest_abi.backup_type=dsr::parse_backup_type(profile::save_type);
        config.deterministic_rtc=true;config.rtc_epoch_seconds=946684800;
        profile::configure(config);
        profile::verify_input(config.rom_path);
        dsr::Session session(config);profile::initialize(session.machine());
        std::map<uint64_t,dsr::InputState> inputs;
        if(!script.empty()) {
            std::ifstream file(script);if(!file)throw std::runtime_error("could not read input script");
            uint64_t frame;unsigned buttons;int x,y;
            while(file>>frame>>buttons>>x>>y) {
                if(buttons>4095 || x< -1 || x>255 || y< -1 || y>191 || (x==-1)!=(y==-1))
                    throw std::runtime_error("invalid scripted input");
                dsr::InputState input;input.buttons=uint16_t(buttons);input.pen_down=x>=0;
                input.pen_x=x;input.pen_y=y;inputs[frame]=input;
            }
            if(!file.eof())throw std::runtime_error("malformed input script");
        }
        std::ofstream pcm;
        if(!audio_path.empty()){pcm.open(audio_path,std::ios::binary);if(!pcm)throw std::runtime_error("could not open audio output");}
#ifdef NDS_WITH_SDL
        std::unique_ptr<Display> display;if(!headless)display=std::make_unique<Display>();
        uint64_t deadline=SDL_GetPerformanceCounter();
#endif
        uint64_t audio_samples=0;
        for(uint64_t frame=0;!frames || frame<frames;++frame) {
            dsr::InputState input;
            if(const auto found=inputs.find(frame);found!=inputs.end())input=found->second;
#ifdef NDS_WITH_SDL
            if(display && !display->input(input))break;
#endif
            session.step(input);audio_samples+=session.audio_frames();
            // Commit dirty cartridge bytes during play as well as on exit.
            // The runtime writes atomically and retains dirty data for retry
            // if the destination is temporarily unwritable.
            if((frame+1)%60==0)session.flush_save();
            if(pcm.is_open()) {
                for(size_t i=0;i<session.audio_frames()*2;++i){const auto value=uint16_t(session.audio_data()[i]);pcm.put(char(value));pcm.put(char(value>>8));}
                if(!pcm)throw std::runtime_error("could not write audio output");
            }
#ifdef NDS_WITH_SDL
            if(display) {
                display->present(session);
                deadline+=uint64_t(double(SDL_GetPerformanceFrequency())/59.8261);
                const auto now=SDL_GetPerformanceCounter();
                if(deadline>now)SDL_Delay(uint32_t((deadline-now)*1000/SDL_GetPerformanceFrequency()));
                else if(now-deadline>SDL_GetPerformanceFrequency()/2)deadline=now;
            }
#endif
        }
        if(!session.flush_save())throw std::runtime_error("could not flush cartridge save");
        if(diagnostics) {
            auto& machine=session.machine();
            std::cerr<<machine.debug_status()<<'\n';
            for(auto id:{dsr::CpuId::Arm9,dsr::CpuId::Arm7}) {
                std::cerr<<(id==dsr::CpuId::Arm9 ? "ARM9" : "ARM7")<<" IO";
                for(uint32_t address:{0x04000004u,0x04000006u,0x04000100u,0x04000102u,
                                      0x04000104u,0x04000106u,0x04000184u})
                    std::cerr<<" "<<std::hex<<address<<"="<<machine.read16(id,address);
                std::cerr<<std::dec<<'\n';
                std::cerr<<(id==dsr::CpuId::Arm9 ? "ARM9" : "ARM7")<<" DMA/card";
                for(uint32_t address:{0x040000b0u,0x040000b4u,0x040000b8u,
                    0x040000bcu,0x040000c0u,0x040000c4u,0x040000c8u,0x040000ccu,0x040000d0u,
                    0x040000d4u,0x040000d8u,0x040000dcu,0x040001a0u,0x040001a4u})
                    std::cerr<<" "<<std::hex<<address<<"="<<machine.read32(id,address);
                std::cerr<<std::dec<<'\n';
            }
        }
        if(!capture.empty()) {
            std::filesystem::create_directories(capture);
            ppm(capture/"top.ppm",session.screen_top());ppm(capture/"bottom.ppm",session.screen_bottom());
        }
        if(!memory_dump.empty()) {
            std::filesystem::create_directories(memory_dump);
            struct Region { const char* name;dsr::CpuId cpu;uint32_t address,size; };
            auto& machine=session.machine();
            const uint32_t dtcm=dsr::dsr_mrc(&machine.cpu(dsr::CpuId::Arm9),15,0,9,1,0,0)&0xfffff000u;
            for(const auto region:{Region{"main.bin",dsr::CpuId::Arm9,0x02000000,0x400000},
                                   Region{"arm7.bin",dsr::CpuId::Arm7,0x03800000,0x10000},
                                   Region{"dtcm.bin",dsr::CpuId::Arm9,dtcm,0x4000}}) {
                std::ofstream file(memory_dump/region.name,std::ios::binary);
                for(uint32_t i=0;i<region.size;i+=4) {
                    const auto value=machine.read32(region.cpu,region.address+i);
                    for(unsigned j=0;j<4;++j)file.put(char(value>>(j*8)));
                }
                if(!file)throw std::runtime_error("could not write memory capture");
            }
        }
        std::cout<<"{\"frames\":"<<session.frame_count()<<",\"ticks\":"<<session.ticks()
                 <<",\"top_hash\":"<<hash(session.screen_top())<<",\"bottom_hash\":"<<hash(session.screen_bottom())
                 <<",\"audio_frames\":"<<audio_samples<<",\"observed\":[";
        for(unsigned i=0;i<profile::observation_count;++i)
            std::cout<<(i?",":"")<<session.machine().read32(dsr::CpuId::Arm9,profile::observations[i]);
        std::cout<<"],\"cpu_pc\":["<<session.machine().debug_cpu_snapshot(dsr::CpuId::Arm9).current_pc
                 <<","<<session.machine().debug_cpu_snapshot(dsr::CpuId::Arm7).current_pc
                 <<"],\"unimplemented_io\":"<<session.machine().unimplemented_io_count()<<"}\n";
    } catch(const std::exception& error) {
        std::cerr<<"DS PC project: "<<error.what()<<'\n';return 1;
    }
}
