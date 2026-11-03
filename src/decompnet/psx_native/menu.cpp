// decomp.wtf's standalone PS1 settings menu (MIT).
#include "psx_runtime_menu.h"
#include "psx_disc_tray.h"
#include "cheats.hpp"
#include "desktop_font.hpp"
#include <algorithm>
#include <cstdio>

// One definition keeps catalog initialization out of inline COMDAT sections.
namespace ps1_host {
#include "cheat_catalog.inc"
}

namespace {
bool opened=false,fallback=true;
int page=0,selected=0,disc=1;
std::string status;
constexpr int width=800,height=520;
uint32_t image[width*height];
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
int rows() {return page==1?(int)ps1_host::cheats.size()+1:page==2?3:3;}
void accept() {
    if(page==0) {
        if(selected==0){page=1;selected=0;}
        else if(selected==1){page=2;selected=0;disc=std::max(1,psx_disc_tray_mounted_disc());}
        else opened=false;
    } else if(page==1) {
        if(selected==(int)ps1_host::cheats.size()){page=0;selected=0;}
        else ps1_host::cheat_set(selected,!ps1_host::cheats[selected].enabled);
    } else {
        if(selected==0)disc=disc%std::max(1,psx_disc_tray_disc_count())+1;
        else if(selected==1)psx_runtime_menu_insert();
        else {page=0;selected=1;}
    }
}
}
extern "C" {
void psx_runtime_menu_init(void) {opened=false;fallback=true;page=selected=0;disc=1;}
int psx_runtime_menu_open(void) {
    if(!fallback)return 0;
    opened=true;page=selected=0;status.clear();++ps1_host::cheat_menu_openings;return 1;
}
void psx_runtime_menu_close(void) {opened=false;}
int psx_runtime_menu_is_open(void) {return opened;}
void psx_runtime_menu_input(int input,int repeat) {
    if(!opened)return;
    if(input==PSX_MENU_BACK||input==PSX_MENU_TOGGLE) {
        if(page){page=0;selected=0;}else opened=false;
    } else if(input==PSX_MENU_UP)selected=(selected+rows()-1)%rows();
    else if(input==PSX_MENU_DOWN)selected=(selected+1)%rows();
    else if(input==PSX_MENU_ACCEPT&&!repeat)accept();
    else if(page==2&&selected==0&&(input==PSX_MENU_LEFT||input==PSX_MENU_RIGHT)) {
        const int count=std::max(1,psx_disc_tray_disc_count());
        disc=(disc-1+(input==PSX_MENU_RIGHT?1:-1)+count)%count+1;
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
    text(24,22,page==1?"Settings / Cheats":page==2?"Settings / Discs":"Game settings",0xfff1f5ff,3,35);
    text(24,68,"Arrows: select   Enter: change   Esc: back",0xffafbed7);
    const int first=selected>7?selected-7:0;
    for(int row=0;row<8&&first+row<rows();++row) {
        const int index=first+row,y=104+row*36;
        if(index==selected)fill(20,y-5,760,32,0xff364867);
        std::string label;
        if(page==0)label=index==0?"Cheats":index==1?"Discs":"Resume game";
        else if(page==1) {
            if(index==(int)ps1_host::cheats.size())label="Back";
            else {
                const auto &entry=ps1_host::cheats[index];
                label=std::string(entry.enabled?"[ON]  ":"[OFF] ")+entry.name;
            }
        } else label=index==0?"Selected disc: "+std::to_string(disc):index==1?"Insert disc and resume":"Back";
        text(28,y,label,0xffedf2ff);
    }
    if(page==1&&selected<(int)ps1_host::cheats.size()) {
        const auto &entry=ps1_host::cheats[selected];
        text(24,409,entry.description.empty()?entry.name:entry.description,0xffafbed7,2,54);
    }
    text(24,445,status.empty()?"Cheats start OFF. Granted items and stats can persist.":status,0xffafbed7);
    text(24,476,"Game paused. F1 resumes; Esc returns to settings.",0xffafbed7);
    *pixels=image;*w=width;*h=height;return 1;
}
}
