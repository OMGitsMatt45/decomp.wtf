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
        std::array<uint32_t,256*192> top,bottom;top.fill(0xff0000ff);bottom.fill(0xff0000ff);
        std::array<uint64_t,256*192> tags{},none{},foreground;foreground.fill(1ull<<32);
        for(size_t i=0;i<tags.size();++i)tags[i]=(scene.serial<<16)|(i+1);
        for(int y=8;y<53;++y)for(int x=4;x<124;++x)foreground[y*256+x]=(1ull<<32)|0xffff0000;
        std::array<uint8_t,192> brightness{};
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
        int x=0,y=0;require(display.touch(850,50,x,y)&&x>=45&&x<=60&&y>=25&&y<=35,"shifted window maps touch back to its native pixels");
        require(!display.touch(80,60,x,y),"map blocks touch-through to the field");
        require(display.touch(480,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"world touch keeps the centered native coordinate frame");
        // One through four party members, including short white bottom borders.
        for(int count=1;count<=4;++count){bottom.fill(0xff000000);for(int i=0;i<count;++i)panel(bottom,12+i*43,49+i*43);
            auto band=video::layout_detail::party_band(bottom.data());require(band.h>=(count-1)*43+38,"all party rows remain ordered and complete");}
        foreground.fill(1ull<<32);frame.top_origins=tags.data();frame.bottom_origins=none.data();
        display.present(frame);pixels=display.read_pixels();
        require(display.layout()=="battle","party border detection selects battle layout");
        require(!display.touch(800,270,x,y),"battle world cannot masquerade as lower-LCD touch");
        require(display.touch(150,400,x,y)&&x>=0&&x<256&&y>=0&&y<192,"battle panels retain lower-screen touch");
        auto* window=SDL_GetWindowFromID(1);require(window,"test window");SDL_SetWindowSize(window,1280,540);SDL_PumpEvents();
        display.present(frame);require(display.width()==1280&&display.world_aspect()>2.3f,"live ultrawide resize updates the camera frustum");
        // Framed standalone pages retain 4:3; unframed full-screen movies keep
        // both native screens. This also exercises top-screen-only pages.
        frame.top_origins=frame.bottom_origins=none.data();bottom.fill(0xff202020);top.fill(0xff0000ff);
        panel(bottom,8,184);display.present(frame);require(display.layout()=="menu","standalone 2D page uses 4:3");
        require(display.touch(640,270,x,y)&&std::abs(x-128)<=1&&std::abs(y-96)<=1,"standalone page retains touch coordinates");
        bottom.fill(0xff000000);display.present(frame);require(display.layout()=="dual","unframed movies keep both complete LCDs");
        std::cout<<"Optional frustum, visibility, field UI, party rows, touch and ultrawide resize checks passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
    return 0;
}
