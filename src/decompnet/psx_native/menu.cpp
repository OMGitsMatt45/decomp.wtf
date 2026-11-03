// decomp.wtf's standalone PS1 settings menu (MIT).
#include "psx_runtime_menu.h"
#include "psx_disc_tray.h"
#include "host_overlay.h"
#include "host_osd.h"
#include "internal_resolution.h"
#include "cheats.hpp"
#include "desktop_font.hpp"
#include <algorithm>
#include <cstdio>

// One definition keeps catalog initialization out of inline COMDAT sections.
namespace ps1_host {
#include "cheat_catalog.inc"
}

extern "C" int decomp_audio_hq_enabled();
extern "C" int decomp_audio_hq_set(int enabled);

namespace {
bool opened=false,fallback=true;
enum Page { Root, Cheats, Discs, Graphics, Audio };
Page page=Root;
int selected=0,disc=1;
std::string status;
constexpr int width=800,height=520;
uint32_t image[width*height];
constexpr int filters[]={PSX_TEXTURE_FILTER_NEAREST,PSX_TEXTURE_FILTER_BILINEAR,PSX_TEXTURE_FILTER_XBR};
const char* const filter_labels[]={"Nearest","Bilinear","xBR"};
void fill(int x,int y,int w,int h,uint32_t color) {
    for(int row=std::max(0,y);row<std::min(height,y+h);++row)
        for(int col=std::max(0,x);col<std::min(width,x+w);++col)image[row*width+col]=color;
}
void text(int x,int y,const std::string &value,uint32_t color,int scale=2,int limit=54) {
    int n=0;
    for(unsigned char ch:value) {
        if(n++>=limit)break;
        if(ch<32||ch>126)ch='?';
        const auto &glyph=ps1_font::kFont[ch-32];
        for(int row=0;row<8;++row)for(int col=0;col<5;++col)
            if(glyph[row]&(0x80u>>col))fill(x+col*scale,y+row*scale,scale,scale,color);
        x+=7*scale;
    }
}
int rows() {
    if(page==Root)return 5;
    if(page==Cheats)return (int)ps1_host::cheats.size()+1;
    return 3;
}
void back() {
    if(page==Root){opened=false;return;}
    selected=(int)page-1;
    page=Root;
    status.clear();
}
int filter_index(int value) {
    for(int i=0;i<3;++i)if(filters[i]==value)return i;
    return 0;
}
void change_graphics(int direction) {
    PsxHostVideoSettings settings{};
    psx_video_current(&settings);
    if(selected==0) {
        int index=0;
        for(int i=0;i<PSX_IR_PRESET_COUNT;++i)
            if(k_psx_ir_presets[i].value==settings.internal_resolution){index=i;break;}
        index=(index+direction+PSX_IR_PRESET_COUNT)%PSX_IR_PRESET_COUNT;
        settings.internal_resolution=k_psx_ir_presets[index].value;
    } else {
        settings.texture_filter=filters[(filter_index(settings.texture_filter)+direction+3)%3];
    }
    status=psx_video_apply_live(&settings)?"Restart to apply deferred graphics settings.":"";
}
void change_audio(int direction) {
    if(selected==0) {
        host_volume_set(host_volume_get()+5*direction);
        status.clear();
    } else {
        const int applied=decomp_audio_hq_set(!decomp_audio_hq_enabled());
        status=applied==0?"Mixer changed for this session only.":
               applied<0?"Mixer is set by the launch environment.":"";
    }
}
void accept() {
    if(page==Root) {
        if(selected==4){opened=false;return;}
        page=static_cast<Page>(selected+1);
        selected=0;
        if(page==Discs)disc=std::max(1,psx_disc_tray_mounted_disc());
    } else if(page==Cheats) {
        if(selected==(int)ps1_host::cheats.size())back();
        else ps1_host::cheat_set(selected,!ps1_host::cheats[selected].enabled);
    } else if(selected==2) {
        back();
    } else if(page==Discs) {
        if(selected==0)disc=disc%std::max(1,psx_disc_tray_disc_count())+1;
        else psx_runtime_menu_insert();
    } else if(page==Graphics) {
        change_graphics(1);
    } else {
        change_audio(1);
    }
}
}
extern "C" {
void psx_runtime_menu_init(void) {opened=false;fallback=true;page=Root;selected=0;disc=1;}
int psx_runtime_menu_open(void) {
    if(!fallback)return 0;
    opened=true;page=Root;selected=0;status.clear();++ps1_host::cheat_menu_openings;return 1;
}
void psx_runtime_menu_close(void) {opened=false;}
int psx_runtime_menu_is_open(void) {return opened;}
void psx_runtime_menu_input(int input,int repeat) {
    if(!opened)return;
    if(input==PSX_MENU_BACK||input==PSX_MENU_TOGGLE) {
        back();
    } else if(input==PSX_MENU_UP)selected=(selected+rows()-1)%rows();
    else if(input==PSX_MENU_DOWN)selected=(selected+1)%rows();
    else if(input==PSX_MENU_ACCEPT&&!repeat)accept();
    else if(input==PSX_MENU_LEFT||input==PSX_MENU_RIGHT) {
        const int direction=input==PSX_MENU_RIGHT?1:-1;
        if(page==Discs&&selected==0) {
            const int count=std::max(1,psx_disc_tray_disc_count());
            disc=(disc-1+direction+count)%count+1;
        } else if(page==Graphics&&selected<2&&!repeat)change_graphics(direction);
        else if(page==Audio&&selected<2&&(!repeat||selected==0))change_audio(direction);
    }
}
int psx_runtime_menu_selected_disc(void) {return disc;}
int psx_runtime_menu_select_disc(int value) {
    if(!opened||value<1||value>psx_disc_tray_disc_count())return 0;disc=value;return 1;
}
int psx_runtime_menu_insert(void) {
    if(!opened)return 0;
    if(psx_disc_tray_cycle(disc,PSX_DISC_TRAY_ORIGIN_MENU)!=PSX_DISC_TRAY_OK) {
        status="Could not insert disc. Check its image files.";return 0;
    }
    opened=false;return 1;
}
struct RecompRuntimeUi *psx_runtime_menu_model(void) {return nullptr;}
void psx_runtime_menu_set_fallback_enabled(int enabled) {fallback=enabled!=0;if(!fallback)opened=false;}
int psx_runtime_menu_overlay_image(const uint32_t **pixels,int *w,int *h) {
    if(!opened)return 0;
    fill(0,0,width,height,0xff131927);
    const char* const titles[]={"Game settings","Settings / Cheats","Settings / Discs",
                               "Settings / Graphics","Settings / Audio"};
    text(24,22,titles[page],0xfff1f5ff,3,35);
    text(24,68,"Up/Down: select   Left/Right or Enter: change",0xffafbed7);
    PsxHostVideoSettings video{};
    if(page==Graphics)psx_video_current(&video);
    const int first=selected>7?selected-7:0;
    for(int row=0;row<8&&first+row<rows();++row) {
        const int index=first+row,y=104+row*36;
        if(index==selected)fill(20,y-5,760,32,0xff364867);
        std::string label;
        if(page==Root) {
            const char* const labels[]={"Cheats","Discs","Graphics","Audio","Resume game"};
            label=labels[index];
        } else if(page==Cheats) {
            if(index==(int)ps1_host::cheats.size())label="Back";
            else {
                const auto &entry=ps1_host::cheats[index];
                label=std::string(entry.enabled?"[ON]  ":"[OFF] ")+entry.name;
            }
        } else if(page==Discs) {
            label=index==0?"Selected disc: "+std::to_string(disc):index==1?"Insert disc and resume":"Back";
        } else if(index==2) {
            label="Back";
        } else if(page==Graphics) {
            if(index==0) {
                const char* preset=psx_ir_label_for(video.internal_resolution);
                label=std::string("Internal resolution: ")+(preset?preset:"Custom");
            } else label=std::string("Texture filtering: ")+filter_labels[filter_index(video.texture_filter)];
        } else {
            label=index==0?"Master volume: "+std::to_string(host_volume_get())+"%":
                decomp_audio_hq_enabled()?"Sound mixer: Enhanced":"Sound mixer: Original";
        }
        text(28,y,label,0xffedf2ff);
    }
    if(page==Cheats&&selected<(int)ps1_host::cheats.size()) {
        const auto &entry=ps1_host::cheats[selected];
        text(24,409,entry.description.empty()?entry.name:entry.description,0xffafbed7,2,54);
    }
    const char* note=page==Cheats?"Cheats start OFF. Granted items and stats can persist.":
        page==Audio?"Enhanced mixing uses verified audio when available.":
        page==Graphics?"Nearest filtering keeps sprite and text edges sharp.":"";
    text(24,445,status.empty()?note:status,0xffafbed7);
    text(24,476,"Game paused. F1 resumes; Esc returns to settings.",0xffafbed7);
    *pixels=image;*w=width;*h=height;return 1;
}
}
