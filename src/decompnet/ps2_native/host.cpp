// SPDX-License-Identifier: MIT
#include "ps2_runtime.h"
#include "runtime/ee_scheduler.h"
#include "runtime/ps2_native_iop.h"
#include "runtime/ps2_pad_host.h"
#include "gfx/backends/sdlgpu/sdlgpu_backend.h"
#include "gfx/backends/sdlgpu/sdlgpu_input.h"
#include "game_config.hpp"
#include "decomp_disc_files.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>

namespace fs=std::filesystem;
namespace {
std::string quoted(const std::string &text) {
    std::string out="\"";
    for(unsigned char c:text) {
        if(c=='"'||c=='\\'){out+='\\';out+=c;}
        else if(c<32){char b[7];std::snprintf(b,sizeof(b),"\\u%04x",c);out+=b;}
        else out+=c;
    }
    return out+'"';
}
void dimensions(const std::string &text,int &w,int &h) {
    char extra;
    if(std::sscanf(text.c_str(),"%dx%d%c",&w,&h,&extra)!=2||w<64||h<64||w>16384||h>16384)
        throw std::runtime_error("resolution must be WIDTHxHEIGHT within 64..16384");
}
uint64_t positive(const std::string &text) {
    size_t used=0;const auto n=std::stoull(text,&used);
    if(text.empty()||text[0]=='-'||used!=text.size()||!n)throw std::runtime_error("expected a positive count");
    return n;
}
struct Host {
    PS2Runtime *runtime=nullptr;
    dq8::gfx::SdlGpuBackend *gpu=nullptr;
    SDL_Window *window=nullptr;
    SDL_Renderer *software=nullptr;
    SDL_Texture *texture=nullptr;
    dq8::gfx::SdlPadInput pad;
    std::atomic<bool> toggle{false};
    uint64_t frames=0,fields=0,last_field=UINT64_MAX,limit=0,seconds=0,pumps=0,resize_frame=0;
    uint32_t source_width=0,source_height=0;
    int drawable_width=0,drawable_height=0,resize_width=0,resize_height=0;
    bool fullscreen=false,scale_limited=false;
    std::string capture;
    bool captured=false;
    std::chrono::steady_clock::time_point started=std::chrono::steady_clock::now();
    ~Host(){if(texture)SDL_DestroyTexture(texture);if(software)SDL_DestroyRenderer(software);if(software&&window)SDL_DestroyWindow(window);}
    static bool watch(void *data,SDL_Event *event) {
        auto &host=*static_cast<Host*>(data);
        if(event->type==SDL_EVENT_KEY_DOWN&&event->key.scancode==SDL_SCANCODE_F11&&!event->key.repeat)host.toggle=true;
        return true;
    }
    void save(const std::vector<uint8_t> &rgba,uint32_t width,uint32_t height) {
        if(capture.empty()||!width||!height||rgba.size()<uint64_t(width)*height*4)return;
        std::ofstream out(capture,std::ios::binary);
        if(!out)throw std::runtime_error("cannot write frame capture");
        out<<"P6\n"<<width<<' '<<height<<"\n255\n";
        for(uint64_t n=0;n<uint64_t(width)*height;++n)out.write(reinterpret_cast<const char*>(rgba.data()+4*n),3);
        if(!out)throw std::runtime_error("frame capture write failed");
        captured=true;
    }
    bool pump() {
        ++pumps;
        fields=runtime->eeScheduler().currentVSyncTick();
        if(gpu) {
            if(!gpu->pumpEvents())return false;
            uint32_t held=0,pressed=0,sticks=0;gpu->hostPadState(held,pressed,sticks);
            ps2PadPublishHostState(held,pressed,sticks);
            frames=gpu->stats().presents;
        } else {
            SDL_Event event;
            while(SDL_PollEvent(&event)){
                if(event.type==SDL_EVENT_QUIT||event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED)return false;
                pad.handleEvent(event);
            }
            pad.poll(SDL_GetKeyboardState(nullptr),(SDL_GetWindowFlags(window)&SDL_WINDOW_INPUT_FOCUS)!=0);
            uint32_t held=0,pressed=0,sticks=0;pad.read(held,pressed,sticks);
            ps2PadPublishHostState(held,pressed,sticks);
            std::vector<uint8_t> rgba;uint32_t w=0,h=0;
            if(runtime->gs().copyLatchedHostPresentationFrame(rgba,w,h)&&w&&h) {
                if(w!=source_width||h!=source_height){
                    if(texture)SDL_DestroyTexture(texture);
                    texture=SDL_CreateTexture(software,SDL_PIXELFORMAT_RGBA32,SDL_TEXTUREACCESS_STREAMING,w,h);
                    if(!texture)throw std::runtime_error(SDL_GetError());
                    SDL_SetRenderLogicalPresentation(software,w,h,SDL_LOGICAL_PRESENTATION_LETTERBOX);
                    source_width=w;source_height=h;
                }
                if(!SDL_UpdateTexture(texture,nullptr,rgba.data(),w*4))throw std::runtime_error(SDL_GetError());
                SDL_RenderClear(software);SDL_RenderTexture(software,texture,nullptr,nullptr);SDL_RenderPresent(software);
                if(fields!=last_field){++frames;last_field=fields;}
                if(!captured&&!capture.empty()&&(!limit||frames+2>=limit))save(rgba,w,h);
            }
        }
        if(toggle.exchange(false)){
            fullscreen=!fullscreen;
            if(!SDL_SetWindowFullscreen(window,fullscreen))throw std::runtime_error(SDL_GetError());
        }
        if(resize_frame&&frames>=resize_frame){
            if(!SDL_SetWindowSize(window,resize_width,resize_height))throw std::runtime_error(SDL_GetError());
            resize_frame=0;
        }
        if(!SDL_GetWindowSizeInPixels(window,&drawable_width,&drawable_height))throw std::runtime_error(SDL_GetError());
        if(gpu){
            const auto state=gpu->stats();
            source_width=state.sourceWidth;source_height=state.sourceHeight;
            if(source_width&&source_height){
                const uint32_t desired=std::max<uint32_t>(1,static_cast<uint32_t>(std::ceil(std::max(
                    double(drawable_width)/source_width,double(drawable_height)/source_height))));
                const uint32_t scale=std::min<uint32_t>(desired,16);
                scale_limited=desired>scale;
                if(gpu->activeResolutionScale()!=scale)gpu->requestResolutionScale(scale);
            }
            if(!capture.empty()&&(!limit||frames+2>=limit)&&!capture_requested&&source_width&&source_height){
                capture_requested=true;gpu->requestCapture(false,[this](dq8::gfx::SdlGpuCapture image){save(image.rgba,image.width,image.height);});
            }
        }
        return !(limit&&frames>=limit) && !(seconds&&std::chrono::steady_clock::now()-started>=std::chrono::seconds(seconds));
    }
    bool capture_requested=false;
    std::string callback_error;
    static bool callback(void *data){
        auto &host=*static_cast<Host*>(data);
        try{return host.pump();}
        catch(const std::exception &error){host.callback_error=error.what();return false;}
        catch(...){host.callback_error="unknown presentation failure";return false;}
    }
};
}

int main(int argc,char **argv) {
    fs::path root=fs::current_path(),report;
    std::string renderer=decomp_ps2_game::renderer,error,fallback;
    Host host;int width=0,height=0;
    std::unique_ptr<dq8::gfx::SdlGpuBackend> gpu;
    std::unique_ptr<PS2Runtime> runtime;
    int result=0;
    try {
        for(int n=1;n<argc;++n){
            const std::string key=argv[n];
            auto value=[&](){if(++n>=argc)throw std::runtime_error("missing option value: "+key);return std::string(argv[n]);};
            if(key=="--project")root=fs::u8path(value());
            else if(key=="--renderer")renderer=value();
            else if(key=="--report")report=fs::u8path(value());
            else if(key=="--frames")host.limit=positive(value());
            else if(key=="--seconds")host.seconds=positive(value());
            else if(key=="--capture")host.capture=value();
            else if(key=="--resolution")dimensions(value(),width,height);
            else if(key=="--resize"){
                const auto text=value();const auto colon=text.find(':');
                if(colon==std::string::npos)throw std::runtime_error("resize must be FRAME:WIDTHxHEIGHT");
                host.resize_frame=positive(text.substr(0,colon));dimensions(text.substr(colon+1),host.resize_width,host.resize_height);
            }
            else if(key=="--fullscreen")host.toggle=true;
            else throw std::runtime_error("unknown option: "+key);
        }
        if(renderer!="auto"&&renderer!="vulkan"&&renderer!="software")throw std::runtime_error("renderer must be auto, vulkan or software");
        root=fs::absolute(root);
        if(!fs::exists(root/"game/assets.json")){
            fs::path candidate=fs::u8path(SDL_GetBasePath());
            for(int n=0;n<4&&!fs::exists(candidate/"game/assets.json");++n)candidate=candidate.parent_path();
            if(fs::exists(candidate/"game/assets.json"))root=candidate;
        }
        if(!fs::is_regular_file(root/"assets/identity.json"))throw std::runtime_error("prepare your owner assets with tools/extract_assets.py first");
        SDL_SetHint(SDL_HINT_GPU_DRIVER,"vulkan");
        if(!SDL_Init(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD))throw std::runtime_error(SDL_GetError());
        if(!width){
            float x=0,y=0;SDL_GetGlobalMouseState(&x,&y);SDL_Point point{int(x),int(y)};
            const auto display=SDL_GetDisplayForPoint(&point);SDL_Rect bounds{};
            if(!SDL_GetDisplayUsableBounds(display,&bounds))throw std::runtime_error(SDL_GetError());
            width=std::max(64,bounds.w*4/5);height=std::max(64,bounds.h*4/5);
        }
        if(renderer!="software"){
            std::string reason;gpu=dq8::gfx::createSdlGpuBackend(reason);
            if(gpu&&!gpu->openWindow(decomp_ps2_game::title,width,height,reason))gpu.reset();
            if(!gpu){if(renderer=="vulkan")throw std::runtime_error("required Vulkan renderer failed: "+reason);fallback=reason;}
        }
        if(gpu){host.gpu=gpu.get();host.window=gpu->window();}
        else{
            host.window=SDL_CreateWindow(decomp_ps2_game::title,width,height,SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIGH_PIXEL_DENSITY);
            if(!host.window)throw std::runtime_error(SDL_GetError());
            host.software=SDL_CreateRenderer(host.window,"software");
            if(!host.software)throw std::runtime_error(SDL_GetError());
            std::string reason;if(!host.pad.initialize(reason))throw std::runtime_error(reason);
        }
        if(!SDL_AddEventWatch(Host::watch,&host))throw std::runtime_error(SDL_GetError());
        runtime=std::make_unique<PS2Runtime>();host.runtime=runtime.get();
        runtime->setExternalPresenter(Host::callback,&host);
        if(!runtime->initialize(decomp_ps2_game::title))throw std::runtime_error("PS2 runtime initialization failed");
        if(gpu)runtime->gs().setRasterBackend(std::move(gpu));
        runtime->setMissingFunctionPolicy(PS2Runtime::MissingFunctionPolicy::Stop);
        if(!runtime->loadELF((root/"assets/cd"/decomp_ps2_game::boot).string()))throw std::runtime_error("owner boot ELF failed to load");
        const uint32_t top=runtime->guestHeapHardLimit();
        if(top<decomp_ps2_game::runtime_arena_bytes||decomp_ps2_game::loaded_end>top-decomp_ps2_game::runtime_arena_bytes)
            throw std::runtime_error("PS2 runtime arena overlaps owner load memory; review this input's memory profile");
        const uint32_t ceiling=top-decomp_ps2_game::runtime_arena_bytes;
        runtime->setGuestHeapCeiling(ceiling);runtime->configureGuestHeap(ceiling,top);
        auto paths=PS2Runtime::getIoPaths();paths.cdRoot=root/"assets/cd";paths.mcRoot=root/"saves";
        fs::create_directories(paths.mcRoot);
        if(decomp_ps2_game::has_disc){
            paths.cdImage=root/"assets/disc.img";
            if(fs::is_regular_file(root/"assets/disc.path")){
                std::ifstream reference(root/"assets/disc.path");std::string path;std::getline(reference,path);
                if(path.empty()||!reference)throw std::runtime_error("invalid external disc reference");
                paths.cdImage=fs::u8path(path);
                if(!paths.cdImage.is_absolute())throw std::runtime_error("external disc reference must be absolute");
            }
            decomp_ps2::disc::mount(paths.cdImage,decomp_ps2_game::files,decomp_ps2_game::sector_size,decomp_ps2_game::data_skip,decomp_ps2_game::disc_type);
        }
        PS2Runtime::setIoPaths(paths);
        ps2_native_iop::setModules(*runtime,decomp_ps2_game::iop_modules);
        host.started=std::chrono::steady_clock::now();runtime->run();
        if(!host.callback_error.empty())throw std::runtime_error(host.callback_error);
        if(runtime->decompMissingFunctions||runtime->decompExecutionFailures)throw std::runtime_error("guest execution failed; see runtime diagnostics and report");
        if(!host.capture.empty()&&!host.captured)throw std::runtime_error("the run produced no requested frame capture");
    }catch(const std::exception &failure){error=failure.what();std::fprintf(stderr,"error: %s\n",error.c_str());result=1;}
    if(!report.empty()){
        std::ofstream out(report);
        const auto stats=host.gpu?host.gpu->stats():dq8::gfx::SdlGpuStats{};
        out<<"{\n  \"schema\":\"decomp.wtf.ps2-run/v1\",\n  \"success\":"<<(result?"false":"true")
           <<",\n  \"error\":"<<quoted(error)<<",\n  \"renderer\":"<<quoted(host.gpu?"vulkan":"software")
           <<",\n  \"software_fallback\":"<<quoted(fallback)<<",\n  \"drawable\":["<<host.drawable_width<<','<<host.drawable_height<<']'
           <<",\n  \"source\":["<<host.source_width<<','<<host.source_height<<']'
           <<",\n  \"internal_scale\":"<<(host.gpu?host.gpu->activeResolutionScale():1)
           <<",\n  \"scale_limited\":"<<(host.scale_limited?"true":"false")
           <<",\n  \"guest_fields\":"<<host.fields<<",\n  \"presented_frames\":"<<host.frames<<",\n  \"gpu_primitives\":"<<stats.primitivesDrawn
           <<",\n  \"gpu_presents\":"<<stats.presents<<",\n  \"disc_read_bytes\":"<<decomp_ps2::disc::read_bytes
           <<",\n  \"disc_type\":"<<decomp_ps2::disc::medium()
           <<",\n  \"missing_functions\":"<<(runtime?runtime->decompMissingFunctions.load():0)
           <<",\n  \"execution_failures\":"<<(runtime?runtime->decompExecutionFailures.load():0)
           <<",\n  \"ee_interpreter\":false,\n  \"iop_interpreter\":true,\n  \"vu_interpreter\":true,\n  \"runtime_compilation\":false\n}\n";
        if(!out){std::fprintf(stderr,"error: cannot write run report\n");result=1;}
    }
    SDL_RemoveEventWatch(Host::watch,&host);
    // The runtime owns the GPU backend. Destroy the software host and its pad
    // before SDL is shut down; no queued GPU callback outlives the host.
    return result;
}
