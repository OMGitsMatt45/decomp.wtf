// decomp.wtf host integration (MIT). Included after the pinned runtime helpers.
#include <fstream>
#include <sstream>
#include <iomanip>
#include <limits>
#include "defaults.hpp"
#ifdef PSX_SDL3
#include <SDL3/SDL_opengl.h>
#else
#include <SDL_opengl.h>
#endif

extern "C" uint64_t decomp_native_dispatches;
extern "C" uint64_t decomp_module_dispatches[];
extern "C" const unsigned decomp_module_count;
static const CPUState *decomp_cpu=nullptr;
static uint64_t decomp_limit=0, decomp_switch_frame=0, decomp_resize_frame=0;
static int decomp_switch_index=0, decomp_width=0, decomp_height=0;
static int decomp_resize_w=0, decomp_resize_h=0;
static bool decomp_fullscreen=false, decomp_require_gpu=decomp_default_require_gpu;
static std::string decomp_report_path, decomp_capture_path;
static std::vector<uint32_t> decomp_observe;

static void decomp_gpu_error() {
    const char *message="OpenGL GPU rendering was required but is unavailable. Use --renderer software to select compatibility mode.";
    std::fprintf(stderr,"%s\n",message);
    if(!g_headless&&!g_hidden_window)
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR,"GPU renderer unavailable",message,sdl_window);
}

static int decomp_active_display() {
#ifdef PSX_SDL3
    float x=0,y=0;SDL_GetGlobalMouseState(&x,&y);
    const SDL_Point point={(int)x,(int)y};
    const SDL_DisplayID found=SDL_GetDisplayForPoint(&point);
    return (int)(found?found:SDL_GetPrimaryDisplay());
#else
    int x=0,y=0;SDL_GetGlobalMouseState(&x,&y);
    const SDL_Point point={x,y};const int found=SDL_GetPointDisplayIndex(&point);
    return found>=0?found:0;
#endif
}
static void decomp_opening_size(int *w,int *h,int num,int den) {
    SDL_Rect bounds={};
    const int valid=SDL_GetDisplayUsableBounds(decomp_active_display(),&bounds)==0&&bounds.w>0&&bounds.h>0;
    psx_window_size(w,h,num,den,valid,bounds.w,bounds.h);
}
static void decomp_place_window(SDL_Window *window) {
    SDL_Rect bounds={};int w=0,h=0;
    if(SDL_GetDisplayUsableBounds(decomp_active_display(),&bounds)!=0)return;
    SDL_GetWindowSize(window,&w,&h);
    SDL_SetWindowPosition(window,bounds.x+(bounds.w-w)/2,bounds.y+(bounds.h-h)/2);
#ifdef PSX_SDL3
    SDL_SyncWindow(window);
#endif
}

static uint64_t decomp_number(const char *value) {
    char *end=nullptr;
    if(!value||!*value||*value=='-') { std::fprintf(stderr,"invalid numeric host option\n");std::exit(2); }
    const auto result=std::strtoull(value,&end,0);
    if(!end||*end) { std::fprintf(stderr,"invalid numeric host option: %s\n",value);std::exit(2); }
    return result;
}
static void decomp_size(const char *value,int &w,int &h) {
    char tail=0;
    if(std::sscanf(value,"%dx%d%c",&w,&h,&tail)!=2||w<64||h<64||w>16384||h>16384) {
        std::fprintf(stderr,"resolution must be WIDTHxHEIGHT (64..16384)\n");std::exit(2);
    }
}
static void decomp_parse(int &argc,char **argv) {
    int kept=1;
    for(int i=1;i<argc;i++) {
        const std::string arg=argv[i];
        const auto next=[&](){if(i+1>=argc){std::fprintf(stderr,"missing value for %s\n",argv[i]);std::exit(2);}return argv[++i];};
        if(arg=="--frames") {decomp_limit=decomp_number(next());if(!decomp_limit)std::exit(2);}
        else if(arg=="--report")decomp_report_path=next();
        else if(arg=="--capture")decomp_capture_path=next();
        else if(arg=="--resolution")decomp_size(next(),decomp_width,decomp_height);
        else if(arg=="--fullscreen")decomp_fullscreen=true;
        else if(arg=="--observe") {
            const uint64_t value=decomp_number(next());
            if(value>0xffffffffu||(value&3u)||(value&0x1fffffffu)>0x1ffffcu)std::exit(2);
            decomp_observe.push_back((uint32_t)value);
        } else if(arg=="--switch-disc") {
            const std::string value=next();const auto split=value.find(':');
            if(split==std::string::npos)std::exit(2);
            decomp_switch_frame=decomp_number(value.substr(0,split).c_str());
            decomp_switch_index=(int)decomp_number(value.substr(split+1).c_str());
            if(decomp_switch_index<1||decomp_switch_index>16)std::exit(2);
        } else if(arg=="--resize") {
            const std::string value=next();const auto split=value.find(':');
            if(split==std::string::npos)std::exit(2);
            decomp_resize_frame=decomp_number(value.substr(0,split).c_str());
            decomp_size(value.substr(split+1).c_str(),decomp_resize_w,decomp_resize_h);
        } else if(arg=="--renderer") {
            char *option=argv[i];
            const char *value=next();
            if(!std::strcmp(value,"auto")) {static char gl[]="opengl";argv[i]=gl;decomp_require_gpu=false;}
            else if(!std::strcmp(value,"opengl"))decomp_require_gpu=true;
            else if(!std::strcmp(value,"software"))decomp_require_gpu=false;
            else {std::fprintf(stderr,"renderer must be auto, opengl or software\n");std::exit(2);}
            argv[kept++]=option;argv[kept++]=argv[i];
        } else argv[kept++]=argv[i];
    }
    argc=kept;argv[kept]=nullptr;
}
static std::string decomp_json(const char *value) {
    std::ostringstream out;out<<'"';
    for(const unsigned char c:std::string(value?value:"")) {
        if(c=='"'||c=='\\')out<<'\\'<<(char)c;
        else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<(unsigned)c;
        else out<<(char)c;
    }
    out<<'"';return out.str();
}
static bool decomp_event(const SDL_Event &event) {
    if(event.type!=SDL_KEYDOWN||event.key.repeat)return false;
#ifdef PSX_SDL3
    const auto key=event.key.key;
#else
    const auto key=event.key.keysym.sym;
#endif
    if(key==SDLK_F11) {
        psx_window_fullscreen_set(sdl_window,&s_window_fullscreen,s_window_fullscreen.mode?0:1);
        return true;
    }
    if((key==SDLK_F9||key==SDLK_F10)&&cdrom_disc_roster_count()>1) {
        const int count=cdrom_disc_roster_count(),direction=key==SDLK_F10?1:-1;
        const int index=(cdrom_disc_selected()-1+direction+count)%count+1;
        if(!cdrom_disc_select(index))std::fprintf(stderr,"could not mount disc %d\n",index);
        else std::fprintf(stdout,"decomp.wtf: inserted disc %d of %d\n",index,count);
        return true;
    }
    return false;
}
static bool decomp_capture(int dw,int dh) {
    if(decomp_capture_path.empty())return true;
    GpuDisplayInfo di;gpu_get_display_info(&di);
    const int scale=di.depth24?1:(gr_scale()>0?gr_scale():1);
    int sw=(int)di.width*scale,sh=di.depth24?(int)di.screen_height:(int)di.height*scale;
    if(sw<=0||sh<=0||(uint64_t)sw*sh>96u*1024u*1024u)return false;
    std::vector<uint32_t> pixels((size_t)sw*sh,0);
    rt_acquire("decomp capture");
    int got=0;
    if(di.depth24) {
        // FMVs pack RGB888 bytes in the CPU VRAM mirror. The geometry FBO is
        // deliberately not an RGB888 scanout surface; use the same decoder as
        // normal presentation, then fit that video canvas to the drawable.
        gpu_depth24_stage_scanout(&di,pixels.data(),(uint32_t)sw,(uint32_t)g_video_depth24_trailing_margin);
        got=1;
    } else if(gr_backend()==GR_BACKEND_OPENGL) {
        int w=0,h=0;
        got=gl_renderer_read_display_hires((int)di.display_x,(int)di.display_y,(int)di.width,(int)di.height,
            pixels.data(),(int)pixels.size(),&w,&h);
        if(got>0){sw=w;sh=h;}
    } else got=gr_render_display_hires(pixels.data(),sw*4,(int)di.display_x,(int)di.display_y,(int)di.width,(int)di.height);
    rt_release();
    if(got<=0)return false;
    if(dw<=0||dh<=0){dw=sw;dh=sh;}
    const double fit=std::min((double)dw/sw,(double)dh/sh);
    const int w=std::max(1,(int)(sw*fit)),h=std::max(1,(int)(sh*fit));
    const int ox=(dw-w)/2,oy=(dh-h)/2;
    std::ofstream file(std::filesystem::u8path(decomp_capture_path),std::ios::binary);
    file<<"P6\n"<<dw<<' '<<dh<<"\n255\n";
    for(int y=0;y<dh;y++)for(int x=0;x<dw;x++) {
        uint32_t color=0;
        if(x>=ox&&x<ox+w&&y>=oy&&y<oy+h)color=pixels[(size_t)((y-oy)*sh/h)*sw+(x-ox)*sw/w];
        const char rgb[]={(char)(color>>16),(char)(color>>8),(char)color};file.write(rgb,3);
    }
    return file.good();
}
static void decomp_frame_end() {
    extern uint64_t s_frame_count;
    if(decomp_require_gpu&&gr_backend()!=GR_BACKEND_OPENGL) {
        decomp_gpu_error();std::exit(1);
    }
    if(decomp_switch_frame&&s_frame_count>=decomp_switch_frame) {
        decomp_switch_frame=0;
        if(!cdrom_disc_select(decomp_switch_index)){std::fprintf(stderr,"disc switch failed\n");std::exit(1);}
    }
    if(decomp_resize_frame&&s_frame_count>=decomp_resize_frame&&sdl_window) {
        decomp_resize_frame=0;SDL_SetWindowSize(sdl_window,decomp_resize_w,decomp_resize_h);
    }
    SDL_Window *window=sdl_window?sdl_window:s_headless_gl_window;
    int dw=0,dh=0;if(window)SDL_GL_GetDrawableSize(window,&dw,&dh);
    SDL_DisplayMode monitor={};
#ifdef PSX_SDL3
    if(window)SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(window),&monitor);
#else
    if(window)SDL_GetCurrentDisplayMode(SDL_GetWindowDisplayIndex(window),&monitor);
#endif
    if(sdl_window&&g_gl_active&&effective_internal_resolution()==PSX_IR_DISPLAY) {
        const int wanted=psx_resolve_internal_scale_ss_cap(PSX_IR_DISPLAY,g_video_ref_lines,dh,
            GL_MAX_INTERNAL_SCALE,display_supersample(sdl_window),g_video_match_max_lines);
        if(wanted!=g_video_requested_scale) {
            g_video_requested_scale=wanted;
            const int applied=gl_renderer_set_internal_scale_live(wanted);
            if(applied>0){g_video_scale=applied;dynres_setup();}
        }
    }
    if(!decomp_limit||s_frame_count<decomp_limit)return;
    memcard_flush_all();spu_catch_up();
    if(memcard_last_flush_result(0)<0||memcard_last_flush_result(1)<0) {
        std::fprintf(stderr,"memory-card flush failed\n");std::exit(1);
    }
    if(!decomp_capture(dw,dh)){std::fprintf(stderr,"capture failed\n");std::exit(1);}
    SpuDebugInfo audio;spu_debug_info(&audio);
    GpuDisplayInfo display;gpu_get_display_info(&display);
    const bool gl=gr_backend()==GR_BACKEND_OPENGL;
    const char *device="";
    if(gl){rt_acquire("decomp report");device=(const char*)glGetString(GL_RENDERER);}
    std::ostringstream out;
    out<<"{\"schema\":\"decomp.wtf.ps1-run/v1\",\"execution_model\":\"hybrid\",\"runtime_compilation\":false,\"frames\":"<<s_frame_count
       <<",\"renderer\":"<<decomp_json(gl?"opengl":"software")<<",\"device\":"<<decomp_json(device)
       <<",\"drawable_width\":"<<dw<<",\"drawable_height\":"<<dh<<",\"internal_scale\":"<<gr_scale()
       <<",\"fullscreen\":"<<(s_window_fullscreen.mode?"true":"false")
       <<",\"monitor_width\":"<<monitor.w<<",\"monitor_height\":"<<monitor.h
       <<",\"depth24\":"<<(display.depth24?"true":"false")
       <<",\"software_fallback\":"<<(!g_headless&&!gl&&g_video_renderer==1?"true":"false")
       <<",\"native_dispatches\":"<<decomp_native_dispatches<<",\"interpreted_instructions\":"<<g_dirty_ram_insns_run
       <<",\"pc\":"<<(decomp_cpu?decomp_cpu->pc:0)<<",\"ra\":"<<(decomp_cpu?decomp_cpu->gpr[31]:0)
       <<",\"last_store_pc\":"<<g_debug_last_store_pc
       <<",\"disc_index\":"<<cdrom_disc_selected()<<",\"disc_count\":"<<cdrom_disc_roster_count()
       <<",\"disc_sectors\":"<<cdrom_mounted_sector_count()<<",\"audio_frames\":"<<audio.render_frames
       <<",\"audio_nonzero_frames\":"<<audio.nonzero_frames<<",\"observed\":[";
    if(gl)rt_release();
    for(size_t i=0;i<decomp_observe.size();i++)out<<(i?",":"")<<psx_read_word(decomp_observe[i]);
    out<<"],\"module_dispatches\":[";
    for(unsigned i=0;i<decomp_module_count;i++)out<<(i?",":"")<<decomp_module_dispatches[i];
    out<<"],\"registers\":[";
    for(int i=0;i<32;i++)out<<(i?",":"")<<(decomp_cpu?decomp_cpu->gpr[i]:0);
    out<<"]}\n";
    if(!decomp_report_path.empty()) {
        std::ofstream file(std::filesystem::u8path(decomp_report_path));file<<out.str();
        if(!file.good()){std::fprintf(stderr,"report write failed\n");std::exit(1);}
    } else std::fputs(out.str().c_str(),stdout);
    std::fflush(stdout);std::exit(0);
}
