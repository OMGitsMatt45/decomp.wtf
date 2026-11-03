// decomp.wtf host integration (MIT). Included after the pinned runtime helpers.
#include <fstream>
#include <sstream>
#include <iomanip>
#include <limits>
#include "defaults.hpp"
#include "cheats.hpp"
#include <map>
#ifdef PSX_SDL3
#include <SDL3/SDL_opengl.h>
#else
#include <SDL_opengl.h>
#endif

extern "C" uint64_t decomp_native_dispatches;
extern "C" uint64_t decomp_module_dispatches[];
extern "C" const unsigned decomp_module_count;
extern "C" uint64_t decomp_copy_dispatches,decomp_kernel_stub_dispatches;
static const CPUState *decomp_cpu=nullptr;
static uint64_t decomp_limit=0, decomp_switch_frame=0, decomp_resize_frame=0;
static int decomp_switch_index=0, decomp_width=0, decomp_height=0;
static int decomp_resize_w=0, decomp_resize_h=0;
static bool decomp_fullscreen=false, decomp_require_gpu=decomp_default_require_gpu;
static std::string decomp_report_path, decomp_capture_path;
static std::vector<uint32_t> decomp_observe;
static uint32_t decomp_coverage_pc=0;
static std::map<uint64_t,int> decomp_inputs;
static int decomp_exit_status=0;
#ifdef DECOMP_PSX_NATIVE_ONLY
static constexpr const char *decomp_execution_model="static-recompiled";
#else
static constexpr const char *decomp_execution_model="reference";
#endif
static bool decomp_bounded_run() { return decomp_limit>0; }

extern "C" int decomp_audio_hq_enabled() {
    return spu_shadow_enabled();
}

extern "C" int decomp_audio_hq_set(int enabled) {
    if(std::getenv("PSX_AUDIO_SHADOW"))return -1;
    g_audio_spu_hq=enabled!=0;
    spu_shadow_set_enabled(g_audio_spu_hq);
    spu_shadow_reset();
    if(g_overlay_settings_path.empty())return 0;
    try {
        auto settings=PSXRecompV4::load_user_settings(g_overlay_settings_path);
        if(settings.parse_error)return 0;
        settings.spu_hq=g_audio_spu_hq;
        settings.has_spu_hq=true;
        return quality_save_user_settings(g_overlay_settings_path,settings);
    } catch (...) {
        return 0;
    }
}

static void decomp_gpu_error() {
    const char *message="OpenGL GPU rendering was required but is unavailable. Use --renderer software to select compatibility mode.";
    std::fprintf(stderr,"%s\n",message);
    if(!g_headless&&!g_hidden_window&&!decomp_bounded_run())
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
#ifdef DECOMP_PSX_NATIVE_ONLY
    const char *snapshot=std::getenv("PSX_LOAD_SLOT");
    if(snapshot&&*snapshot){
        std::fputs("Snapshots are unavailable in this native build. Use the game's own save menu.\n",stderr);
        std::exit(2);
    }
    const char *force=std::getenv("PSX_FORCE_INTERP");
    if(force&&*force&&*force!='0'){
        std::fputs("PSX_FORCE_INTERP requires the optional ps1_probe reference target.\n",stderr);std::exit(2);
    }
#endif
    int kept=1;
    for(int i=1;i<argc;i++) {
        const std::string arg=argv[i];
        const auto next=[&](){if(i+1>=argc){std::fprintf(stderr,"missing value for %s\n",argv[i]);std::exit(2);}return argv[++i];};
        if(arg=="--frames") {decomp_limit=decomp_number(next());if(!decomp_limit)std::exit(2);}
        else if(arg=="--input-script") {
            std::ifstream file(std::filesystem::u8path(next()));
            if(!file){std::fputs("cannot open input script\n",stderr);std::exit(2);}
            std::string line;
            while(std::getline(file,line)) {
                if(line.empty()||line[0]=='#')continue;
                std::istringstream row(line);std::string frame,mask,extra;
                if(!(row>>frame>>mask)||(row>>extra)){std::fputs("input script requires FRAME ACTIVE_LOW_PAD_MASK\n",stderr);std::exit(2);}
                const auto at=decomp_number(frame.c_str());
                int value=-1;
                if(mask!="LIVE") {
                    const auto parsed=decomp_number(mask.c_str());
                    if(parsed>0xffffu)std::exit(2);
                    value=(int)parsed;
                }
                if(decomp_inputs.size()>=100000u||!decomp_inputs.emplace(at,value).second)std::exit(2);
            }
        }
        else if(arg=="--key-tap-frames") {
            const auto frames=decomp_number(next());
            if(frames<1||frames>30){std::fputs("key tap duration must be 1..30 frames\n",stderr);std::exit(2);}
            decomp_keybinds_set_tap_frames((unsigned)frames);
        }
        else if(arg=="--cheat") {
            const auto index=decomp_number(next());
            if(index>=ps1_host::cheats.size()){std::fputs("cheat index outside catalog\n",stderr);std::exit(2);}
            ps1_host::cheat_set((size_t)index,true);
        }
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
    const bool menu=psx_runtime_menu_is_open()||savestate_menu_open||psx_rewind_is_open();
    if(menu)decomp_keybinds_clear_pulses();
#ifdef PSX_SDL3
    if(event.type==SDL_EVENT_WINDOW_FOCUS_LOST)decomp_keybinds_clear_pulses();
#else
    if(event.type==SDL_WINDOWEVENT&&event.window.event==SDL_WINDOWEVENT_FOCUS_LOST)decomp_keybinds_clear_pulses();
#endif
    if(event.type!=SDL_KEYDOWN||event.key.repeat)return false;
#ifdef PSX_SDL3
    const auto key=event.key.key;
    const auto scan=event.key.scancode;
#else
    const auto key=event.key.keysym.sym;
    const auto scan=event.key.keysym.scancode;
#endif
    if(std::getenv("DECOMP_PSX_TRACE"))std::fprintf(stderr,
        "decomp.wtf: keydown frame=%llu key=%u scan=%u menu=%d\n",
        (unsigned long long)s_frame_count,(unsigned)key,(unsigned)scan,(int)menu);
#ifdef DECOMP_PSX_NATIVE_ONLY
    if(key==SDLK_F7) {
        host_osd_push("Snapshots unavailable. Use the game's own save menu.",5000);
        return true;
    }
#endif
    if(key==SDLK_F1) {
        decomp_keybinds_clear_pulses();
        if(!savestate_menu_open&&!psx_rewind_is_open())psx_runtime_menu_open();
        return true;
    }
    if(key==SDLK_F11) {
        psx_window_fullscreen_set(sdl_window,&s_window_fullscreen,s_window_fullscreen.mode?0:1);
        return true;
    }
    if(key==SDLK_F10&&cdrom_disc_roster_count()>1) {
        const int count=cdrom_disc_roster_count();
        const int index=cdrom_disc_selected()%count+1;
        if(psx_disc_tray_cycle(index,PSX_DISC_TRAY_ORIGIN_MENU)!=PSX_DISC_TRAY_OK)std::fprintf(stderr,"could not mount disc %d\n",index);
        else std::fprintf(stdout,"decomp.wtf: inserted disc %d of %d\n",index,count);
        return true;
    }
    if(!menu){
#ifdef PSX_SDL3
        decomp_keybinds_note_keydown(event.key.scancode);
#else
        decomp_keybinds_note_keydown(event.key.keysym.scancode);
#endif
    }
    return false;
}
static void decomp_input_trace(int override) {
    if(!std::getenv("DECOMP_PSX_TRACE"))return;
    static int last_buttons=-1,last_connected=-1,last_analog=-1,last_kind=-1;
    const int buttons=sio_get_pad_buttons_slot(0),connected=sio_get_pad_connected(0);
    const int analog=sio_get_pad_analog(0),kind=g_players[0].kind;
    if(buttons==last_buttons&&connected==last_connected&&analog==last_analog&&kind==last_kind)return;
    std::fprintf(stderr,"decomp.wtf: input frame=%llu buttons=%04x connected=%d analog=%d kind=%d override=%d\n",
        (unsigned long long)s_frame_count,buttons,connected,analog,kind,override);
    last_buttons=buttons;last_connected=connected;last_analog=analog;last_kind=kind;
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
static int decomp_script_input() {
    extern uint64_t s_frame_count;
    if(decomp_inputs.empty()||psx_netplay_active())return -1;
    const auto cursor=decomp_inputs.upper_bound(s_frame_count);
    const int value=cursor==decomp_inputs.begin()?0xffff:std::prev(cursor)->second;
    static bool driven=false;
    if(value>=0){sio_set_pad_connected(0,1);driven=true;}
    else if(driven){sio_set_pad_state_slot(0,0xffff);driven=false;}
    return value;
}
static void decomp_frame_end() {
    extern uint64_t s_frame_count;
#ifdef DECOMP_PSX_NATIVE_ONLY
    savestate_set_title_blocked(1);
#endif
    ps1_host::cheat_tick();
    if(s_frame_count%60==0&&std::getenv("DECOMP_PSX_TRACE")) {
        std::fprintf(stderr,"decomp.wtf: frame=%llu pc=%08x ra=%08x native=%llu interpreted=%llu observed=",
            (unsigned long long)s_frame_count,decomp_cpu?decomp_cpu->pc:0,decomp_cpu?decomp_cpu->gpr[31]:0,
            (unsigned long long)decomp_native_dispatches,(unsigned long long)g_dirty_ram_insns_run);
        for(auto address:decomp_observe)std::fprintf(stderr," %08x",psx_read_word(address));
        std::fputc('\n',stderr);std::fflush(stderr);
    }
    if(decomp_require_gpu&&gr_backend()!=GR_BACKEND_OPENGL) {
        decomp_gpu_error();std::exit(1);
    }
    if(decomp_switch_frame&&s_frame_count>=decomp_switch_frame) {
        decomp_switch_frame=0;
        if(psx_disc_tray_cycle(decomp_switch_index,PSX_DISC_TRAY_ORIGIN_MENU)!=PSX_DISC_TRAY_OK){std::fprintf(stderr,"disc switch failed\n");std::exit(1);}
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
    if(!decomp_exit_status&&(!decomp_limit||s_frame_count<decomp_limit))return;
    if(!decomp_exit_status){memcard_flush_all();spu_catch_up();}
    if(!decomp_exit_status&&(memcard_last_flush_result(0)<0||memcard_last_flush_result(1)<0)) {
        std::fprintf(stderr,"memory-card flush failed\n");std::exit(1);
    }
    if(!decomp_exit_status&&!decomp_capture(dw,dh)){std::fprintf(stderr,"capture failed\n");std::exit(1);}
    SpuDebugInfo audio;spu_debug_info(&audio);
    SpuShadowInfo mixer;spu_shadow_get_info(&mixer);
    GpuDisplayInfo display;gpu_get_display_info(&display);
    const bool gl=gr_backend()==GR_BACKEND_OPENGL;
    const char *device="";
    if(gl){rt_acquire("decomp report");device=(const char*)glGetString(GL_RENDERER);}
    std::ostringstream out;
    out<<"{\"schema\":\"decomp.wtf.ps1-run/v1\",\"execution_model\":"<<decomp_json(decomp_execution_model)
       <<",\"runtime_compilation\":false,\"frames\":"<<s_frame_count
       <<",\"renderer\":"<<decomp_json(gl?"opengl":"software")<<",\"device\":"<<decomp_json(device)
       <<",\"drawable_width\":"<<dw<<",\"drawable_height\":"<<dh<<",\"internal_scale\":"<<gr_scale()
       <<",\"fullscreen\":"<<(s_window_fullscreen.mode?"true":"false")
       <<",\"monitor_width\":"<<monitor.w<<",\"monitor_height\":"<<monitor.h
       <<",\"depth24\":"<<(display.depth24?"true":"false")
       <<",\"depth24_trailing_margin\":"<<g_video_depth24_trailing_margin
       <<",\"software_fallback\":"<<(!g_headless&&!gl&&g_video_renderer==1?"true":"false")
       <<",\"native_dispatches\":"<<decomp_native_dispatches<<",\"interpreted_instructions\":"<<g_dirty_ram_insns_run
       <<",\"copied_dispatches\":"<<decomp_copy_dispatches<<",\"kernel_bridge_dispatches\":"<<decomp_kernel_stub_dispatches
       <<",\"coverage_misses\":"<<(decomp_exit_status?1:0)<<",\"coverage_pc\":"<<decomp_coverage_pc
       <<",\"pc\":"<<(decomp_cpu?decomp_cpu->pc:0)<<",\"ra\":"<<(decomp_cpu?decomp_cpu->gpr[31]:0)
       <<",\"last_store_pc\":"<<g_debug_last_store_pc
       <<",\"disc_index\":"<<cdrom_disc_selected()<<",\"disc_count\":"<<cdrom_disc_roster_count()
       <<",\"settings_openings\":"<<ps1_host::cheat_menu_openings<<",\"cheat_toggles\":"<<ps1_host::cheat_toggles
       <<",\"scripted_input\":"<<(!decomp_inputs.empty()?"true":"false")
       <<",\"pad0_buttons\":"<<sio_get_pad_buttons_slot(0)<<",\"pad0_connected\":"<<sio_get_pad_connected(0)
       <<",\"disc_sectors\":"<<cdrom_mounted_sector_count()<<",\"audio_frames\":"<<audio.render_frames
       <<",\"audio_nonzero_frames\":"<<audio.nonzero_frames
       <<",\"audio_hq_enabled\":"<<(mixer.enabled?"true":"false")
       <<",\"audio_hq_verified\":"<<(mixer.proven?"true":"false")
       <<",\"audio_hq_fallbacks\":"<<mixer.pauses
       <<",\"audio_hq_applied_frames\":"<<mixer.applied_frames
       <<",\"master_volume\":"<<host_volume_get()
       <<",\"texture_filter\":"<<g_video_texfilter<<",\"observed\":[";
    if(gl)rt_release();
    for(size_t i=0;i<decomp_observe.size();i++)out<<(i?",":"")<<psx_read_word(decomp_observe[i]);
    out<<"],\"coverage_words\":[";
    const uint32_t coverage_physical=decomp_coverage_pc&0x1fffffffu;
    const uint32_t coverage_segment=decomp_coverage_pc&0xe0000000u;
    if(decomp_exit_status&&g_psx_ram&&!(decomp_coverage_pc&3u)&&coverage_physical<0x200000u&&
       (coverage_segment==0u||coverage_segment==0x80000000u||coverage_segment==0xa0000000u)) {
        const uint32_t count=std::min(64u,(0x200000u-coverage_physical)/4u);
        for(uint32_t i=0;i<count;i++) {
            uint32_t word;std::memcpy(&word,g_psx_ram+coverage_physical+i*4u,4);
            out<<(i?",":"")<<word;
        }
    }
    out<<"],\"module_dispatches\":[";
    for(unsigned i=0;i<decomp_module_count;i++)out<<(i?",":"")<<decomp_module_dispatches[i];
    out<<"],\"registers\":[";
    for(int i=0;i<32;i++)out<<(i?",":"")<<(decomp_cpu?decomp_cpu->gpr[i]:0);
    out<<"],\"cheats\":[";
    for(size_t i=0;i<ps1_host::cheats.size();++i) {
        const auto &entry=ps1_host::cheats[i];
        out<<(i?",":"")<<"{\"name\":"<<decomp_json(entry.name.c_str())
           <<",\"enabled\":"<<(entry.enabled?"true":"false")
           <<",\"applications\":"<<entry.applications<<",\"changes\":"<<entry.changes<<"}";
    }
    out<<"]}\n";
    if(!decomp_report_path.empty()) {
        std::ofstream file(std::filesystem::u8path(decomp_report_path));file<<out.str();
        if(!file.good()){std::fprintf(stderr,"report write failed\n");std::exit(1);}
    } else std::fputs(out.str().c_str(),stdout);
    std::fflush(stdout);std::exit(decomp_exit_status);
}
extern "C" void decomp_psx_missing_native(CPUState *cpu,uint32_t pc){
    std::fprintf(stderr,"decomp.wtf: missing native PS1 code at %08x (ra=%08x). "
        "Regenerate source coverage; reference diagnostics use ps1_probe.\n",pc,cpu?cpu->gpr[31]:0);
    if(cpu)cpu->pc=pc;
    decomp_cpu=cpu;decomp_coverage_pc=pc;decomp_exit_status=3;
    decomp_frame_end();std::exit(3);
}
