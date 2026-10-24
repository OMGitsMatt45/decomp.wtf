// SPDX-License-Identifier: CC0-1.0. Original GPU/presentation qualification.
#include "video.hpp"
#include <dsr/gpu2d.h>
#include <fstream>
#include <iostream>
#include <stdexcept>

void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
void send(dsr::Gpu3D& gpu,uint8_t command,std::initializer_list<uint32_t> words={0}) {
    for(auto value:words)gpu.io_write(0x04000400u+uint32_t(command)*4,value,32);
}
void vertex(dsr::Gpu3D& gpu,int16_t x,int16_t y,int16_t z) {
    send(gpu,0x23,{uint32_t(uint16_t(x))|(uint32_t(uint16_t(y))<<16),uint16_t(z)});
}
void capture(const char* name,const video::Display& display) {
    const auto pixels=display.read_pixels();std::ofstream file(name,std::ios::binary);
    file<<"P6\n"<<display.width()<<' '<<display.height()<<"\n255\n";
    for(auto pixel:pixels)for(unsigned shift:{16u,8u,0u})file.put(char(pixel>>shift));
}
int main() {
    try {
        require(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_EVENTS)==0,SDL_GetError());
        dsr::MachineConfig config;config.direct_boot=false;dsr::Machine machine(config);
        auto& gpu=machine.gpu3d();gpu.set_capture_opaque_only(true);
        gpu.io_write(0x04000580,0xbfff0000,32);gpu.io_write(0x04000354,0x7fff,32);
        send(gpu,0x10,{0});send(gpu,0x15);send(gpu,0x10,{1});send(gpu,0x15);
        send(gpu,0x29,{0x001f00c0});send(gpu,0x20,{0x03e0});send(gpu,0x40,{1});
        // This extends beyond the DS frustum. Unified rendering must draw the
        // raw geometry outside the old 256x192 viewport, not stretch its pixels.
        vertex(gpu,-12288,-12288,0);vertex(gpu,12288,-12288,0);
        vertex(gpu,12288,12288,0);vertex(gpu,-12288,12288,0);send(gpu,0x41);
        send(gpu,0x50);gpu.run(100000);gpu.vblank_start();gpu.render_start();
        auto scene=video::Scene::capture(machine);
        require(scene.vertices.size()==4&&scene.polygons.size()==1,"capture original submitted quad");
        require(scene.vertices[0].clip[0]<-1&&scene.safe[128+96*256],"capture preclip geometry and opaque eligibility");
        gpu.reset(); // A borrowed geometry or mask pointer would now be wrong.
        require(scene.vertices[0].clip[0]<-1&&scene.safe[128+96*256],"capture owns geometry and masks");
        std::array<uint32_t,256*192> top,bottom;top.fill(0xff0000ff);bottom.fill(0xff0000ff);
        std::array<uint8_t,256*192> mask;mask.fill(1);
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x){mask[y*256+x]=0;bottom[y*256+x]=0xffff0000;}
        video::Display display({"opengl","unified",960,540,false,true});
        video::Frame frame{&scene,top.data(),bottom.data(),mask.data(),false};
        display.present(frame);
        auto pixels=display.read_pixels();
        require(display.renderer()=="opengl"&&display.unified()&&display.polygons_drawn()>0,"draw original geometry with OpenGL");
        require(display.width()==960&&display.height()==540,"drawable resolution");
        require(pixels[10+10*960]==0xff00ff00,"new geometry appears beyond both DS screen bounds");
        require(pixels[305+275*960]==0xffff0000,"UI keeps its original pixels in the unified camera");
        require(pixels[800+30*960]==0xff0000ff,"secondary LCD UI stays accessible in an inset");
        capture("unified.ppm",display);
        int x,y;require(display.touch(480,405,x,y)&&x==128&&y==96,"touch maps the bottom-camera region");
        require(!display.touch(10,10,x,y),"extended scenery is not a DS touch coordinate");
        auto red=scene;for(auto& v:red.vertices)v.color={63,0,0};frame.scene=&red;frame.on_top=true;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[10+10*960]==0xff00ff00,"alternating top camera does not replace the retained bottom camera");
        // A menu/2D scene must clear the retained view and show both LCDs.
        mask.fill(0);display.present(frame);pixels=display.read_pixels();
        require(!display.unified()&&pixels[480+135*960]==0xff0000ff,"menus restore both screens without stale geometry");
        // GPU drawing in dual view uses only the matching mask and cannot cover UI.
        SDL_KeyboardEvent key{};key.type=SDL_KEYDOWN;key.keysym.scancode=SDL_SCANCODE_F6;display.key(key);
        mask.fill(1);mask[0]=0;frame.scene=&scene;frame.on_top=false;display.present(frame);
        pixels=display.read_pixels();require(!display.unified(),"F6 changes presentation");
        require(pixels[480+405*960]==0xff00ff00&&pixels[480+135*960]==0xff0000ff,"GPU dual-screen mapping");
        capture("dual.ppm",display);
        require(display.touch(480,405,x,y)&&x==128&&y==96,"dual touch mapping");
        // Textured geometry is shaded on the GPU, using actual texture coordinates.
        auto textured=scene;const uint32_t parameter=7u<<26;auto& polygon=textured.polygons[0];polygon.texture=parameter;
        video::Texture texture;texture.param=parameter;texture.width=texture.height=8;
        for(unsigned i=0;i<64;++i)texture.rgba.insert(texture.rgba.end(),{255,0,0,255});
        textured.textures.push_back(texture);for(auto& v:textured.vertices){v.color={63,63,63};v.u=v.v=1;}
        frame.scene=&textured;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffff0000,"GPU texture sampling and modulation");
        auto partial=scene;partial.polygons[0].viewport=0x5f7f0000;frame.scene=&partial;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[350+300*960]==0xff00ff00&&pixels[550+300*960]==0xff0000ff&&pixels[350+500*960]==0xff0000ff,
            "partial DS viewports clip at their own bounds in dual mode");
        auto occluded=scene;occluded.clear_depth=0;frame.scene=&occluded;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"DS clear depth rejects geometry behind it");
        // A conservative unsupported effect keeps the complete software frame.
        textured.supported=false;frame.scene=&textured;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"unsupported effects retain complete native output");
        require(display.polygons_drawn()>=4,"multiple actual geometry draw calls");
        // Resize the actual SDL window to a different aspect ratio. Rendering
        // and touch must immediately follow the new drawable, without export,
        // a fixed internal render target or an application restart.
        auto* window=SDL_GetWindowFromID(1);require(window,"original SDL window exists");
        SDL_SetWindowSize(window,640,480);SDL_PumpEvents();frame.scene=&scene;
        display.key(key);display.present(frame);pixels=display.read_pixels();
        require(display.width()==640&&display.height()==480&&pixels.size()==640*480,"GPU adapts to drawable resize");
        require(pixels[10+10*640]==0xff00ff00,"extended geometry adapts to a different screen aspect ratio");
        require(display.touch(320,360,x,y)&&x==128&&y==96,"touch adapts to the resized drawable");
        auto wire=scene;wire.polygons[0].attr&=~(31u<<16);wire.clear_color=0x001f7c00;frame.scene=&wire;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[320+360*640]==0xff0000ff,"wireframe quads have no triangulation diagonal");
        std::cout<<"GPU geometry, unified camera, UI, texture, camera retention and touch checks passed: "<<display.device()<<'\n';
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
    SDL_Quit();return 0;
}
