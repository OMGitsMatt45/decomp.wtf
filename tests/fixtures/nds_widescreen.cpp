// SPDX-License-Identifier: CC0-1.0. Original frustum/layout regression scenes.
#include "video.hpp"
#include "dynamic_layout.hpp"
#include <dsr/gpu2d.h>
#include <iostream>
#include <stdexcept>
#include <cmath>

void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
void send(dsr::Gpu3D& gpu,uint8_t cmd,std::initializer_list<uint32_t> args={0}) {
    for(auto value:args)gpu.io_write(0x04000400+unsigned(cmd)*4,value,32);
}
void vertex(dsr::Gpu3D& gpu,int16_t x,int16_t y) {send(gpu,0x23,{uint32_t(uint16_t(x))|uint32_t(uint16_t(y))<<16,0});}
void quad(dsr::Gpu3D& gpu,int16_t left,int16_t right) {
    send(gpu,0x40,{1});vertex(gpu,left,-2048);vertex(gpu,right,-2048);vertex(gpu,right,2048);vertex(gpu,left,2048);send(gpu,0x41);
}
void panel(std::array<uint32_t,256*192>& pixels,int top,int bottom) {
    for(int y=top;y<=bottom;++y)for(int x=8;x<248;++x)pixels[y*256+x]=y==top||y==bottom||x==8||x==247?0xffffffff:0xff505050;
}
int main() {
    try {
        dsr::MachineConfig config;config.direct_boot=false;dsr::Machine machine(config);auto& gpu=machine.gpu3d();
        gpu.set_host_widescreen(16.f/9);
        gpu.io_write(0x04000580,0xbfff0000,32);gpu.io_write(0x04000354,0x7fff,32);
        send(gpu,0x10,{0});send(gpu,0x16,{4096,0,0,0,0,4096,0,0,0,0,4096,4096,0,0,0,4096});
        send(gpu,0x10,{1});send(gpu,0x15);send(gpu,0x29,{0x001f00c0});send(gpu,0x20,{0x03e0});
        quad(gpu,-2048,2048);quad(gpu,4506,5325);
        send(gpu,0x50);gpu.run(100000);gpu.vblank_start();gpu.render_start();
        require(gpu.geometry_view().polygon_count==1&&gpu.geometry_view().vertex_count==4,"host side geometry cannot consume native RAM");
        require(gpu.widescreen_geometry_view().polygon_count==2&&gpu.widescreen_geometry_view().vertex_count==8,"retain a primitive entirely outside the native frustum");
        require(!gpu.geometry_view().polygon_overflow&&!gpu.geometry_view().vertex_overflow,"host buffers cannot set native overflow flags");
        auto scene=video::Scene::capture(machine);
        require(scene.widescreen&&scene.polygons.size()==2&&scene.order.size()==2,"capture owns and sorts the wider geometry");
        auto box=[&]{send(gpu,0x70,{uint32_t(4608)|(uint32_t(uint16_t(-256))<<16),uint32_t(512)<<16,uint32_t(512)|(uint32_t(256)<<16)});gpu.run(10000);return (gpu.io_read(0x04000600,32)&2)!=0;};
        require(!box(),"observation alone leaves BOX_TEST unchanged");
        gpu.set_host_widescreen(16.f/9,true);require(box(),"explicit wider perspective visibility includes side objects");
        send(gpu,0x10,{0});send(gpu,0x15);gpu.run(10000);require(!box(),"orthographic BOX_TEST remains native");
        gpu.reset();require(gpu.host_widescreen_aspect()>1.7f&&gpu.widescreen_geometry_view().polygon_count==0,"reset keeps configuration and invalidates optional geometry");
        gpu.set_host_widescreen(0);require(gpu.host_widescreen_aspect()==0,"default frustum can be restored");
        // Borrowed runtime buffers are no longer relevant to the owned scene.
        require(scene.vertices.size()==8,"captured wider scene survives reset");
        // Two far-plane gradient strips jointly form a sky. Neither strip is
        // individually full height; both must remain part of the world canvas.
        for(const auto range:std::array<std::array<float,2>,2>{{{{-1,.3f}},{{.3f,1}}}}) {
            dsr::Gpu3DPolygon p;p.count=4;p.viewport=0xbfff0000;p.attr=0x001f00c0;
            const float positions[4][2]={{-1,range[0]},{1,range[0]},{1,range[1]},{-1,range[1]}};
            for(unsigned n=0;n<4;++n){p.index[n]=uint16_t(scene.vertices.size());dsr::Gpu3DVertex v;v.clip={positions[n][0],positions[n][1],.999f,1};v.color={0,0,63};scene.vertices.push_back(v);}
            scene.order.push_back(uint16_t(scene.polygons.size()));scene.polygons.push_back(p);
        }
        std::array<uint32_t,256*192> top,bottom;top.fill(0xff0000ff);bottom.fill(0xff0000ff);
        std::array<uint64_t,256*192> tags{},none{},foreground;foreground.fill(1ull<<32);
        for(size_t i=0;i<tags.size();++i)tags[i]=(scene.serial<<16)|(i+1);
        for(int y=8;y<53;++y)for(int x=4;x<124;++x)foreground[y*256+x]=(1ull<<32)|0xffff0000;
        std::array<uint8_t,192> brightness{};
        for(int yy=7;yy<=53;++yy)for(int xx=3;xx<=124;++xx)if(yy==7||yy==53||xx==3||xx==124) {
            bottom[yy*256+xx]=0xffffffff;foreground[yy*256+xx]=(1ull<<32)|0xffffffff;
        }
        std::deque<video::Scene> history{scene};
        require(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_EVENTS)==0,SDL_GetError());
        video::Options options{"opengl",960,540,false,true};options.dynamic_widescreen=true;
        video::Display display(options);
        video::Frame frame{&history[0],top.data(),bottom.data(),nullptr,false,none.data(),tags.data(),&history,
            foreground.data(),foreground.data(),brightness.data(),brightness.data()};
        display.present(frame);auto pixels=display.read_pixels();
        require(display.layout()=="field"&&display.render_scale()>=2,"dynamic field selected");
        require((pixels[912+270*960]&0x00ff0000)==0&&(pixels[912+270*960]&0x0000ff00)>0x8000,"side geometry visible beyond old DS edge");
        require(pixels[850+50*960]==0xffff0000,"native foreground moves to the upper-right");
        require(pixels[700+200*960]==0xff0000ff,"split sky strips fill the world without a floating background window");
        int x=0,y=0;require(display.touch(850,50,x,y)&&x>=45&&x<=60&&y>=25&&y<=35,"shifted window maps touch back to its native pixels");
        require(!display.touch(80,60,x,y),"map blocks touch-through to the field");
        require(display.touch(480,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"world touch keeps the centered native coordinate frame");
        // One through four party members, including short white bottom borders.
        for(int count=1;count<=4;++count)for(int acting=0;acting<count;++acting) {
            bottom.fill(0xff000000);int end=0;
            for(int i=0;i<count;++i){const int h=i==acting?70:38;panel(bottom,end,end+h-1);end+=h+2;}
            const auto band=video::layout_detail::party_band(bottom.data());
            require(band.y==0&&band.y+band.h>=end-2,"expanded acting member and every command row remain complete");
        }
        for(int count=1;count<=4;++count){bottom.fill(0xff000000);for(int i=0;i<count;++i)panel(bottom,12+i*43,49+i*43);
            auto band=video::layout_detail::party_band(bottom.data());require(band.h>=(count-1)*43+38,"all party rows remain ordered and complete");}
        foreground.fill(1ull<<32);frame.top_origins=tags.data();frame.bottom_origins=none.data();
        for(int y=120;y<192;++y)for(int x=0;x<256;++x) {
            const bool edge=y==120||y==191||x==0||x==255;
            foreground[y*256+x]=(1ull<<32)|(edge?0xffffffff:0xff00ff00);
            if(edge)top[y*256+x]=0xffffffff;
        }
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="battle","party border detection selects battle layout");
        require(!display.touch(800,270,x,y),"battle world cannot masquerade as lower-LCD touch");
        require(display.touch(150,400,x,y)&&x>=0&&x<256&&y>=0&&y<192,"battle panels retain lower-screen touch");
        require(pixels[350+450*960]==0xff505050&&pixels[400+450*960]==0xff00ff00,"battle messages clear the party panels");
        bottom.fill(0xff000000);panel(bottom,0,69);panel(bottom,72,109);
        for(int y=112;y<=180;++y)for(int x=148;x<=245;++x)
            bottom[y*256+x]=y==112||y==180||x==148||x==245?0xffffffff:0xff505050;
        for(int y=10;y<20;++y)for(int x=80;x<90;++x)bottom[y*256+x]=0xffff0000;
        for(int y=168;y<178;++y)for(int x=200;x<210;++x)bottom[y*256+x]=0xffff00ff;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[128+296*960]==0xffff0000&&pixels[297+518*960]==0xffff00ff,"expanded commands and lower nested target list render without clipping");
        require(display.touch(128,296,x,y)&&std::abs(x-85)<=1&&std::abs(y-15)<=1,"expanded command touch remains native");
        require(display.touch(297,518,x,y)&&std::abs(x-205)<=1&&std::abs(y-173)<=1,"nested target-list touch remains native");
        foreground.fill(1ull<<32);
        for(int y=156;y<166;++y){for(int x=20;x<60;++x)foreground[y*256+x]=(1ull<<32)|0xffff0000;
            for(int x=130;x<190;++x)foreground[y*256+x]=(1ull<<32)|0xffffff00;}
        display.present(frame);pixels=display.read_pixels();
        require(pixels[405+488*960]==0xffff0000&&pixels[574+488*960]==0xffffff00,"unframed battle words retain their spacing and clear expanded party panels");
        foreground.fill(1ull<<32);
        for(int y=80;y<92;++y)for(int x=32;x<52;++x)foreground[y*256+x]=(1ull<<32)|0xffff00ff;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[238+242*960]==0xffff00ff,"enemy target marker stays at its world projection instead of a HUD corner");
        // Sprite animation may change size or cross the old y/size thresholds.
        // Its anchor must follow the native world rather than any HUD corner.
        for(int yy:{90,125,135})for(int size:{16,36,50}) {
            foreground.fill(1ull<<32);
            for(int y=yy;y<yy+size&&y<192;++y)for(int x=80;x<80+size;++x)foreground[y*256+x]=(1ull<<32)|0xffff00ff;
            display.present(frame);pixels=display.read_pixels();
            const int px=int(480+(80+size/2.f-128)*540/192.f),py=int((yy+size/2.f)*540/192.f);
            require(pixels[px+py*960]==0xffff00ff,"world sprites keep their position across animation sizes and heights");
        }
        foreground.fill(1ull<<32);bottom.fill(0xffc0a060);
        for(int yy=8;yy<41;++yy)for(int xx=212;xx<244;++xx)foreground[yy*256+xx]=(1ull<<32)|0xffff00ff;
        std::array<video::Frame::HudRegion,1> hud{{{208,0,48,48,true}}};frame.hud_regions=hud;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[925+55*960]==0xffff00ff,"identified fixed HUD buttons retain their corner and smaller scale");
        hud[0].on_top=false;display.present(frame);pixels=display.read_pixels();
        require(pixels[760+67*960]==0xffff00ff,"HUD ownership never relocates sprites on the other LCD");
        frame.hud_regions={};foreground.fill(1ull<<32);
        frame.mode=video::Frame::Mode::Gameplay;frame.auxiliary=video::Frame::Auxiliary::Battle;
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="battle"&&pixels[60+60*960]!=0xffc0a060,"battle setup/results never expose an empty map backdrop");
        for(int yy=72;yy<=110;++yy)for(int xx=32;xx<=223;++xx)
            bottom[yy*256+xx]=yy==72||yy==110||xx==32||xx==223?0xffffffff:0xff505050;
        const auto experience=video::layout_detail::party_band(bottom.data());
        require(experience.x>=28&&experience.x+experience.w<=228,"XP panel crop excludes its wide tan background margins");
        bottom[90*256+100]=bottom[0];
        const auto cropped=video::layout_detail::panel_pixels(bottom.data(),experience);
        require(cropped[experience.y*256+experience.x]==0&&cropped[90*256+100]==bottom[0],"panel exterior becomes transparent without erasing enclosed pixels of the same color");
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="battle"&&display.touch(150,500,x,y),"battle result panel keeps lower-LCD input");
        frame.mode=video::Frame::Mode::Auto;frame.auxiliary=video::Frame::Auxiliary::Auto;
        auto* window=SDL_GetWindowFromID(1);require(window,"test window");SDL_SetWindowSize(window,1280,540);SDL_PumpEvents();
        display.present(frame);require(display.width()==1280&&display.world_aspect()>2.3f,"live ultrawide resize updates the camera frustum");
        // One-screen cinematics keep backdrop and narration in one native
        // frustum. Two separated glyph runs must not be anchored atop each other.
        auto cinema=history.front();cinema.serial+=100;
        for(float center:{-.4f,.4f}) {
            dsr::Gpu3DPolygon p;p.count=4;p.viewport=0xbfff0000;p.attr=0x001f00c0;
            const float xy[4][2]={{center-.1f,-.85f},{center+.1f,-.85f},{center+.1f,-.75f},{center-.1f,-.75f}};
            for(unsigned i=0;i<4;++i){p.index[i]=uint16_t(cinema.vertices.size());dsr::Gpu3DVertex v;v.clip={xy[i][0],xy[i][1],-.5f,1};v.color={63,63,63};cinema.vertices.push_back(v);}
            cinema.order.push_back(uint16_t(cinema.polygons.size()));cinema.polygons.push_back(p);
        }
        history.clear();history.push_back(std::move(cinema));frame.scene=&history.front();
        for(size_t i=0;i<tags.size();++i)tags[i]=(history.front().serial<<16)|(i+1);
        frame.top_origins=none.data();frame.bottom_origins=tags.data();top.fill(0xff000000);bottom.fill(0xff0000ff);
        foreground.fill(1ull<<32);
        for(int y=150;y<158;++y)for(int x=40;x<60;++x){const int i=y*256+x;bottom[i]=0xffffffff;tags[i]=0;foreground[i]=(1ull<<32)|0xffffffff;}
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="cinematic","empty secondary LCD selects cinematic framing");
        require(pixels[496+486*1280]==0xffffffff&&pixels[784+486*1280]==0xffffffff&&pixels[420+433*1280]==0xffffffff,"3D glyph runs and native 2D captions retain their distinct positions");
        require(pixels[80+270*1280]==0xff000000,"cinematic backdrop stays within its authored frustum");
        std::array<uint8_t,192> cinematic_brightness;frame.bottom_brightness=cinematic_brightness.data();
        cinematic_brightness.fill(0x30);bottom.fill(0xffffffff);display.present(frame);pixels=display.read_pixels();
        require(pixels[640+270*1280]==0xffffffff,"captured enhanced scene obeys full brighten");
        cinematic_brightness.fill(0x50);bottom.fill(0xff000000);display.present(frame);pixels=display.read_pixels();
        require(pixels[640+270*1280]==0xff000000,"captured enhanced scene obeys full darken");
        frame.bottom_brightness=brightness.data();
        // Framed standalone pages retain 4:3; unframed full-screen movies keep
        // both native screens. This also exercises top-screen-only pages.
        frame.top_origins=frame.bottom_origins=none.data();bottom.fill(0xff202020);top.fill(0xff0000ff);
        panel(bottom,8,184);display.present(frame);require(display.layout()=="menu","standalone 2D page uses 4:3");
        require(display.touch(640,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"standalone page retains touch coordinates");
        bottom.fill(0xff00ff00);none[0]=(history.front().serial<<16)|1;display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="dual-wide","two active menu pictures retain both LCDs in landscape");
        require(pixels[320+270*1280]==0xff0000ff&&pixels[960+270*1280]==0xff00ff00,"movie pictures retain their source colors and proportions");
        require(!display.touch(320,270,x,y)&&display.touch(960,270,x,y)&&std::abs(x-128)<=1,"landscape LCD pair maps lower-screen touch only");
        none[0]=0;display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="movie"&&pixels[640+135*1280]==0xff0000ff&&pixels[640+405*1280]==0xff00ff00,"paired movie streams retain their original vertical relationship");
        bottom.fill(0xff000000);
        for(int y=150;y<166;++y)for(int x=100;x<150;++x)bottom[y*256+x]=0xffff8000;
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="startup"&&pixels[640+400*1280]==0xff0000ff,"startup picture uses full height before gameplay");
        require(pixels[640+484*1280]==0xffff8000&&display.touch(640,484,x,y)&&x>=124&&x<=126&&y>=157&&y<=159,"startup controls retain source pixels and inverse touch");
        for(int yy:{16,176})for(int xx=12;xx<244;++xx)top[yy*256+xx]=0xffffffff;
        require(video::layout_detail::full_window(top.data()),"bright movie fixture resembles menu borders");
        display.present(frame);require(display.layout()=="startup","Start prompt takes precedence over coincidental movie borders");
        top.fill(0xff0000ff);
        bottom.fill(0xff000000);display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="startup"&&pixels[640+400*1280]==0xff0000ff,"one LCD can remove the Start prompt before the movie picture without changing its framing");
        bottom.fill(0xff00ff00);display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="movie"&&pixels[640+135*1280]==0xff0000ff&&pixels[640+405*1280]==0xff00ff00,"two active movie LCDs replace startup framing on the first frame");
        top.fill(0xff0000ff);bottom.fill(0xff004000);
        for(int y=8;y<=46;++y)for(int x=9;x<=228;++x)
            bottom[y*256+x]=y==8||y==46||x==9||x==228?0xffa4a4a4:0xff202020;
        require(video::layout_detail::has_window(bottom.data()),"partial-height start-menu frame is recognized");
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="menu-wide"&&pixels[320+270*1280]==0xff0000ff,"2D start menu uses a landscape composition instead of movie stacking");
        require(display.touch(960,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"2D landscape menu preserves lower-screen touch");
        for(int phase=0;phase<42;++phase) {
            bottom.fill(0xff004000);
            for(int y=8;y<=46;++y)for(int x=9;x<=228;++x)
                bottom[y*256+x]=y==8||y==46||x==9||x==228?0xffa4a4a4:0xff202020;
            const bool right=phase>=21;const int start=right?224:5,end=right?233:18;
            for(int y=15;y<15+phase%13;++y)for(int x=start;x<end;++x)bottom[y*256+x]=0xffffb000;
            display.present(frame);pixels=display.read_pixels();
            require(display.layout()=="menu-wide"&&pixels[320+270*1280]==0xff0000ff,"animated cursor occlusion cannot switch menu layout");
            require(display.touch(960,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"menu touch mapping stays stable throughout cursor animation");
        }
        // Complete pre-master 2D metadata identifies a menu even when its
        // visible borders disappear during darken/brighten transitions.
        bottom.fill(0xff004000);
        for(int y=8;y<=46;++y)for(int x=9;x<=228;++x)
            bottom[y*256+x]=y==8||y==46||x==9||x==228?0xffa4a4a4:0xff202020;
        const auto unfaded=bottom;
        for(size_t i=0;i<foreground.size();++i)foreground[i]=(1ull<<32)|unfaded[i];
        frame.bottom_foreground=foreground.data();frame.bottom_brightness=cinematic_brightness.data();
        for(unsigned mode:{1u,2u})for(unsigned factor=0;factor<=16;++factor) {
            cinematic_brightness.fill(uint8_t((mode<<5)|factor));
            for(size_t i=0;i<bottom.size();++i) {
                uint32_t p=0xff000000;
                for(unsigned shift:{16u,8u,0u}){const auto c=(unfaded[i]>>shift)&255;
                    p|=(mode==1?c+(255-c)*factor/16:c*(16-factor)/16)<<shift;}
                bottom[i]=p;
            }
            display.present(frame);pixels=display.read_pixels();
            require(display.layout()=="menu-wide","every master brightness level retains the menu arrangement");
            require(pixels[960+270*1280]==bottom[128+96*256],"classification never draws unfaded metadata in place of current pixels");
            require(display.touch(960,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"fading menus keep their native inverse touch mapping");
        }
        std::array<uint32_t,256*192> classified;
        foreground[0]|=2ull<<32;
        require(video::layout_detail::classification_pixels(bottom.data(),foreground.data(),cinematic_brightness.data(),classified)==bottom.data(),"unsupported foreground cannot become a classification picture");
        foreground[0]=(1ull<<32)|0x7f000000;
        require(video::layout_detail::classification_pixels(bottom.data(),foreground.data(),cinematic_brightness.data(),classified)==bottom.data(),"partial foreground cannot become a classification picture");
        frame.bottom_brightness=brightness.data();foreground.fill(1ull<<32);
        bottom.fill(0xff000000);
        for(int y:{8,46})for(int x=9;x<=228;++x)bottom[y*256+x]=0xffa4a4a4;
        for(int y=8;y<=46;++y)bottom[y*256+228]=0xffa4a4a4;
        require(!video::layout_detail::has_window(bottom.data()),"a missing vertical side is not a bounded menu frame");
        bottom.fill(0xff00ff00);display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="movie"&&pixels[640+135*1280]==0xff0000ff&&pixels[640+405*1280]==0xff00ff00,"leaving an animated menu restores the synchronized movie layout immediately");
        // A scene cut may lose replayable polygons before its last native LCD
        // picture or white fade disappears. Render that picture at full height.
        auto cut=frame;cut.scene=nullptr;cut.history=nullptr;
        top.fill(0xff000000);bottom.fill(0xff00ff00);cut.bottom_origins=tags.data();
        display.present(cut);pixels=display.read_pixels();
        require(display.layout()=="cinematic"&&pixels[640+100*1280]==0xff00ff00,"cut without replayable geometry keeps the complete cinematic picture");
        require(display.touch(640,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"native cinematic fallback retains lower-LCD touch");
        bottom.fill(0xffffffff);display.present(cut);pixels=display.read_pixels();
        require(display.layout()=="cinematic"&&pixels[640+100*1280]==0xffffffff,"mixed black and white LCD fades cannot create a second empty pane");
        bottom.fill(0xff00ff00);cut.bottom_origins=none.data();display.present(cut);pixels=display.read_pixels();
        require(display.layout()=="cinematic"&&pixels[640+100*1280]==0xff00ff00,"single-screen cinematic framing survives missing origin metadata");
        top.fill(0xff0000ff);display.present(cut);pixels=display.read_pixels();
        require(display.layout()=="movie"&&pixels[640+135*1280]==0xff0000ff&&pixels[640+405*1280]==0xff00ff00,"an actual two-screen movie is never delayed by cinematic fallback");
        top.fill(0xffffffff);bottom.fill(0xffffffff);
        // A native logo may retain a captured 3D origin even though its LCD
        // composition is a sparse logo on a solid backdrop.
        none[0]=(history.front().serial<<16)|1;
        for(int y=70;y<110;++y)for(int x=75;x<180;++x)top[y*256+x]=0xffa0a0a0;
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="credits-wide"&&pixels[80+270*1280]==0xffffffff&&pixels[640+270*1280]==0xffa0a0a0,"single logo uses the full-height wide canvas with matching backdrop");
        top.fill(0xff000000);bottom.fill(0xff000000);
        for(int yy=0;yy<192;++yy){top[yy*256]=0xff101010;bottom[yy*256]=0xff101010;}
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="credits-wide"&&pixels[640+270*1280]==0xff000000,"asynchronous nearly blank credit fades retain their framing with current pixels");
        top.fill(0xffffffff);bottom.fill(0xffffffff);
        for(int yy=70;yy<110;++yy)for(int xx=75;xx<180;++xx)top[yy*256+xx]=0xffa0a0a0;
        display.present(frame);
        for(int y=60;y<110;++y)for(int x=90;x<170;++x)bottom[y*256+x]=0xffff0000;
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="credits-wide"&&pixels[320+270*1280]==0xffa0a0a0&&pixels[960+270*1280]==0xffff0000,"independent paired logos keep proportions in landscape");
        bottom.fill(0xffffffff);require(!video::layout_detail::full_window(bottom.data()),"uniform white fades are not menu frames");
        frame.mode=video::Frame::Mode::MovieVertical;
        for(int phase=0;phase<24;++phase) {
            top.fill(phase%2?0xff000000:0xffffffff);bottom.fill(phase%3?0xff00ff00:0xff000000);
            if(phase%4==0)panel(bottom,8,184);
            display.present(frame);pixels=display.read_pixels();
            require(display.layout()=="movie","explicit movie context keeps one layout through dark, logo-like and window-like frames");
            require(!display.touch(640,135,x,y)&&display.touch(640,405,x,y)&&std::abs(x-128)<=1,"locked paired movie retains its two-screen order and touch mapping");
        }
        frame.mode=video::Frame::Mode::MenuLandscape;
        display.present(frame);
        require(display.layout()=="menu-wide"&&display.touch(960,270,x,y)&&std::abs(x-128)<=1,"explicit paired menu keeps a tall start page in landscape with native touch");
        frame.mode=video::Frame::Mode::MovieSingle;frame.on_top=true;
        for(int phase=0;phase<24;++phase) {
            top.fill(phase%2?0xff000000:0xffffffff);bottom.fill(0xffff0000);
            if(phase%3==0)panel(top,8,184);
            display.present(frame);pixels=display.read_pixels();
            require(display.layout()=="cinematic"&&pixels[80+270*1280]==0xff000000,"single-screen movie preserves its entire 4:3 frame and side bars through every fade");
            require(pixels[640+270*1280]==top[128+96*256]&&!display.touch(640,270,x,y),"top-screen movie excludes the unused lower LCD and touch");
        }
        frame.mode=video::Frame::Mode::Gameplay;frame.auxiliary=video::Frame::Auxiliary::Map;
        frame.on_top=false;top.fill(0xffff0000);bottom.fill(0xff0000ff);
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="field"&&pixels[640+270*1280]==0xff0000ff&&pixels[80+270*1280]==0xff0000ff,"missing world geometry retains the known primary LCD and fills its fade color");
        require(pixels[80+80*1280]==0xffff0000,"an auxiliary map stays inset during a geometry-free transition");
        std::cout<<"Optional frustum, visibility, field UI, party rows, touch and ultrawide resize checks passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
    return 0;
}
