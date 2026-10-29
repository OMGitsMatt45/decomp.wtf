// SPDX-License-Identifier: CC0-1.0. Original GPU/presentation qualification.
#include "video.hpp"
#include "audio_queue.hpp"
#include <dsr/gpu2d.h>
#include <dsr/rt.h>
#include <dsr/mem.h>
#include <fstream>
#include <iostream>
#include <cmath>
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
void audio_queue_checks() {
    SDL_AudioSpec spec{};spec.freq=48000;spec.channels=2;spec.format=AUDIO_S16SYS;spec.samples=1024;
    const auto device=SDL_OpenAudioDevice(nullptr,0,&spec,nullptr,0);
    require(device!=0,"paused dummy audio device");
    // Newly opened queue-mode devices are paused, so counts are deterministic.
    std::vector<uint8_t> block(4800*4,0x34),backlog(28800*4,0x12);
    for(unsigned i=0;i<3;++i)require(ds_host::queue_game_audio(device,block,48000),"audio admitted through the exact 300ms boundary");
    require(SDL_GetQueuedAudioSize(device)==3*block.size(),"accepted PCM reaches the real SDL queue");
    require(!ds_host::queue_game_audio(device,block,48000),"overflow block is declined");
    require(SDL_GetQueuedAudioSize(device)==3*block.size(),"overflow preserves already queued sound");
    SDL_ClearQueuedAudio(device);
    require(SDL_QueueAudio(device,backlog.data(),Uint32(backlog.size()))==0,"prepare a pre-existing 600ms backlog");
    require(!ds_host::queue_game_audio(device,block,48000),"an existing backlog admits no additional audio");
    require(SDL_GetQueuedAudioSize(device)==backlog.size(),"clock drift never flushes the old backlog");
    SDL_ClearQueuedAudio(device);
    require(ds_host::queue_game_audio(device,{},48000)&&SDL_GetQueuedAudioSize(device)==0,"empty PCM is a no-op");
    bool rejected=false;
    try{ds_host::queue_game_audio(device,std::span<const uint8_t>(block).first(3),48000);}
    catch(const std::runtime_error&){rejected=true;}
    require(rejected,"partial stereo PCM is rejected");
    SDL_CloseAudioDevice(device);
    std::cout<<"SDL audio backlog preservation checks passed\n";
}
int main() {
    try {
        require(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_EVENTS|SDL_INIT_AUDIO)==0,SDL_GetError());
        audio_queue_checks();
        dsr::MachineConfig config;config.direct_boot=false;dsr::Machine machine(config);
        auto& gpu=machine.gpu3d();gpu.set_capture_opaque_only(true);
        gpu.io_write(0x04000580,0xbfff0000,32);gpu.io_write(0x04000354,0x7fff,32);
        send(gpu,0x10,{0});send(gpu,0x15);send(gpu,0x10,{1});send(gpu,0x15);
        send(gpu,0x29,{0x001f00c0});send(gpu,0x20,{0x03e0});send(gpu,0x40,{1});
        // Submit geometry beyond the DS frustum; clip it to the original LCD.
        vertex(gpu,-12288,-12288,0);vertex(gpu,12288,-12288,0);
        vertex(gpu,12288,12288,0);vertex(gpu,-12288,12288,0);send(gpu,0x41);
        send(gpu,0x50);gpu.run(100000);gpu.vblank_start();gpu.render_start();
        auto scene=video::Scene::capture(machine);
        require(scene.vertices.size()==4&&scene.polygons.size()==1,"capture original submitted quad");
        require(scene.vertices[0].clip[0]<-1&&scene.safe[128+96*256],"capture preclip geometry and opaque eligibility");
        const auto raster_serial=gpu.render_serial();gpu.render_start();
        require(gpu.render_serial()==raster_serial+1&&gpu.geometry_view().generation==scene.generation,
            "completed rasters have distinct identities without geometry swaps");
        auto& two=machine.gpu2d();two.set_capture_origin_tracking(true);
        two.io_write(0x04000304,0x820f,16);two.io_write(0x04000240,0x80,8);
        two.io_write(0x04000064,0x81300000,32);
        for(int y=0;y<192;++y)two.render_line(y);two.vblank_start();
        two.io_write(0x04000240,0x81,8);two.io_write(0x04000000,0x10405,32);two.io_write(0x0400000c,0x4084,16);
        two.io_write(0x04000020,256,16);two.io_write(0x04000026,256,16);
        for(int y=0;y<192;++y)two.render_line(y);
        require(two.screen_top_origins()[128+96*256]!=0,"actual Machine captures 3D origin");
        const auto address=0x06000000u+2*(128+96*256);
        dsr::wr16(&machine.cpu(dsr::CpuId::Arm9),address,machine.read16(dsr::CpuId::Arm9,address),0);
        for(int y=0;y<192;++y)two.render_line(y);
        require(two.screen_top_origins()[128+96*256]==0&&two.screen_top_origins()[129+96*256]!=0,
            "emitted CPU store invalidates captured origin through rebuilt fast pages");
        two.set_capture_origin_tracking(false);
        gpu.reset();gpu.render_start();require(gpu.render_serial()>raster_serial+1,"raster identity cannot alias after reset");
        // A borrowed geometry or mask pointer would now be wrong.
        require(scene.vertices[0].clip[0]<-1&&scene.safe[128+96*256],"capture owns geometry and masks");
        std::array<uint32_t,256*192> top,bottom;top.fill(0xff0000ff);bottom.fill(0xff0000ff);
        std::array<uint8_t,256*192> mask;mask.fill(1);
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x){mask[y*256+x]=0;bottom[y*256+x]=0xffff0000;}
        video::Display display({"opengl",960,540,false,true});
        video::Frame frame{&scene,top.data(),bottom.data(),mask.data(),false};
        display.present(frame);
        auto pixels=display.read_pixels();
        require(display.renderer()=="opengl"&&display.polygons_drawn()>0,"draw original geometry with OpenGL");
        require(display.width()==960&&display.height()==540,"drawable resolution");
        require(pixels[10+10*960]==0xff000000,"geometry stays inside the LCD rectangles");
        require(pixels[305+275*960]==0xffff0000,"GPU geometry preserves lower-screen UI");
        require(pixels[480+405*960]==0xff00ff00&&pixels[480+135*960]==0xff0000ff,"GPU two-screen mapping");
        capture("dual.ppm",display);
        int x,y;require(display.touch(480,405,x,y)&&x==128&&y==96,"touch maps the lower LCD");
        require(!display.touch(10,10,x,y)&&!display.touch(480,135,x,y),"letterbox and upper LCD reject touch");
        // A menu/2D scene must retain both complete LCDs.
        mask.fill(0);display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"menus keep original LCD output");
        mask.fill(1);mask[0]=0;
        // Textured geometry is shaded on the GPU, using actual texture coordinates.
        auto textured=scene;textured.control|=1;const uint32_t parameter=7u<<26;auto& polygon=textured.polygons[0];polygon.texture=parameter;
        video::Texture texture;texture.param=parameter;texture.width=texture.height=8;
        for(unsigned i=0;i<64;++i)texture.rgba.insert(texture.rgba.end(),{255,0,0,255});
        textured.textures.push_back(texture);for(auto& v:textured.vertices){v.color={63,63,63};v.u=v.v=1;}
        frame.scene=&textured;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffff0000,"GPU texture sampling and modulation");
        // The uploaded texture remains cached, but display control can turn
        // mapping off while the polygon still carries its texture address.
        auto threshold=textured;threshold.control|=4;threshold.alpha_ref=31;frame.scene=&threshold;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"alpha equal to the enabled reference is rejected");
        threshold.alpha_ref=30;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffff0000,"alpha above the reference passes");
        threshold.alpha_ref=31;threshold.control&=~4u;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffff0000,"disabled alpha test ignores its stored reference");
        auto disabled=textured;disabled.control&=~1u;disabled.textures.clear();frame.scene=&disabled;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffffffff,"disabled texture mapping ignores the previous cached texture");
        disabled.control|=1;disabled.polygons[0].texture=0;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffffffff,"untextured polygons cannot inherit the cache");
        frame.scene=&textured;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xffff0000,"texture mapping can resume from the existing cache");

        auto partial=scene;partial.polygons[0].viewport=0x5f7f0000;frame.scene=&partial;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[350+300*960]==0xff00ff00&&pixels[550+300*960]==0xff0000ff&&pixels[350+500*960]==0xff0000ff,
            "partial DS viewports clip at their own bounds in dual mode");
        auto occluded=scene;occluded.clear_depth=0;frame.scene=&occluded;
        display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"DS clear depth rejects geometry behind it");
        // DS Z maps the far plane to 0xfffffe, below its maximum clear value.
        // OpenGL's ordinary z=1 mapping would incorrectly reject this geometry.
        auto far_plane=scene;for(auto& v:far_plane.vertices)v.clip[2]=v.clip[3];
        frame.scene=&far_plane;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff00ff00,"DS far-plane geometry remains in front of maximum clear depth");
        // A conservative unsupported effect keeps the complete software frame.
        textured.supported=false;frame.scene=&textured;display.present(frame);pixels=display.read_pixels();
        require(pixels[480+405*960]==0xff0000ff,"unsupported effects retain complete native output");
        require(display.polygons_drawn()>=4,"multiple actual geometry draw calls");
        // Resize the actual SDL window to a different aspect ratio. Rendering
        // and touch must immediately follow the new drawable, without export,
        // a fixed internal render target or an application restart.
        auto* window=SDL_GetWindowFromID(1);require(window,"original SDL window exists");
        SDL_SetWindowSize(window,640,480);SDL_PumpEvents();frame.scene=&scene;
        display.present(frame);pixels=display.read_pixels();
        require(display.width()==640&&display.height()==480&&pixels.size()==640*480,"GPU adapts to drawable resize");
        require(pixels[10+10*640]==0xff000000&&pixels[320+360*640]==0xff00ff00,"geometry and letterboxing follow resized LCDs");
        require(display.touch(320,360,x,y)&&x==128&&y==96,"touch adapts to the resized drawable");
        auto wire=scene;wire.polygons[0].attr&=~(31u<<16);wire.clear_color=0x001f7c00;frame.scene=&wire;
        display.present(frame);pixels=display.read_pixels();
        for(int sy=356;sy<364;++sy)for(int sx=316;sx<324;++sx)
            require(pixels[sx+sy*640]==0xff0000ff,"wireframe quads have no triangulation diagonal");
        // Portrait/narrow displays must retain the complete touch/UI rectangle.
        SDL_SetWindowSize(window,320,720);SDL_PumpEvents();frame.scene=&scene;mask.fill(1);
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x)mask[y*256+x]=0;
        display.present(frame);pixels=display.read_pixels();
        require(display.width()==320&&display.height()==720,"portrait drawable resolution");
        require(pixels[2+362*320]==0xffff0000,"portrait layout keeps left-edge UI on screen");
        require(display.touch(160,480,x,y)&&x==128&&y==96,"portrait touch coordinates follow fitted UI");
        // Captured VRAM displays have no live BG0 mask. Re-render the exact
        // older raster for each LCD, at drawable resolution, preserving UI.
        auto old=scene,newer=textured;old.serial=11;newer.serial=12;newer.supported=true;
        std::deque<video::Scene> history{old,newer};
        std::array<uint64_t,256*192> top_tags,bottom_tags;
        top.fill(0xff0000ff);bottom.fill(0xff0000ff);mask.fill(0);
        for(unsigned i=0;i<256*192;++i){top_tags[i]=(11ull<<16)|(i+1);bottom_tags[i]=(12ull<<16)|(i+1);}
        for(unsigned yy=0;yy<16;++yy)for(unsigned xx=0;xx<16;++xx){bottom_tags[yy*256+xx]=0;bottom[yy*256+xx]=0xffffff00;}
        video::Frame archived{nullptr,top.data(),bottom.data(),mask.data(),false,top_tags.data(),bottom_tags.data(),&history};
        SDL_SetWindowSize(window,960,540);SDL_PumpEvents();display.present(archived);pixels=display.read_pixels();
        require(pixels[480+135*960]==0xff00ff00&&pixels[480+405*960]==0xffff0000,
            "two LCDs use their own archived captured raster, without live BG0");
        require(display.captured_pixels()>90000,"captured replay reports active pixels for the current frame");
        require(pixels[305+275*960]==0xffffff00,"captured-3D replay keeps original UI pixels");
        // Coordinates must be applied, rather than stretching the latest scene.
        auto& gradient=history.back();
        for(unsigned i=0;i<64;++i){gradient.textures[0].rgba[i*4]=(i%8)<4?255:0;gradient.textures[0].rgba[i*4+1]=(i%8)<4?0:255;}
        gradient.serial=13;
        for(auto& v:gradient.vertices){v.clip[0]=std::copysign(1.f,v.clip[0]);v.clip[1]=std::copysign(1.f,v.clip[1]);v.u=(v.clip[0]+1)*4;v.v=4;}
        for(unsigned yy=0;yy<192;++yy)for(unsigned xx=0;xx<256;++xx)bottom_tags[yy*256+xx]=(13ull<<16)|(yy*256+255-xx+1);
        SDL_SetWindowSize(window,1031,617);SDL_PumpEvents();display.present(archived);pixels=display.read_pixels();
        require(pixels[412+463*1031]==0xff00ff00&&pixels[618+463*1031]==0xffff0000,
            "captured source coordinates survive mirroring and odd drawable resize");
        for(unsigned yy=90;yy<102;++yy)for(unsigned xx=122;xx<134;++xx)top_tags[yy*256+xx]=0;
        display.present(archived);pixels=display.read_pixels();
        require(pixels[515+154*1031]==0xff0000ff,"invalidated bitmap texels keep native output");
        history.pop_front();display.present(archived);pixels=display.read_pixels();
        require(display.captured_pixels()==256*192,"retired raster metadata is not counted as replayed");
        require(pixels[412+154*1031]==0xff0000ff,"retired raster never aliases a newer captured scene");
        std::cout<<"Captured VRAM raster history, source mapping, UI and resize checks passed\n";
        // Even an unmasked offscreen replay must clip huge submitted vertices
        // to their DS viewport rather than spilling across its clear border.
        {
            auto inset=scene;inset.serial=27;inset.clear_color=(31u<<16)|(31u<<10);
            inset.polygons[0].viewport=(143u<<24)|(191u<<16)|(48u<<8)|64u;
            std::deque<video::Scene> inset_history{inset};
            for(unsigned i=0;i<256*192;++i)top_tags[i]=(27ull<<16)|(i+1);
            video::Frame inset_frame{nullptr,top.data(),bottom.data(),mask.data(),false,top_tags.data(),bottom_tags.data(),&inset_history};
            SDL_SetWindowSize(window,960,540);SDL_PumpEvents();display.present(inset_frame);pixels=display.read_pixels();
            require(pixels[350+135*960]==0xff0000ff&&pixels[480+135*960]==0xff00ff00,
                "offscreen geometry clips to its viewport and retains the clear border");
        }
        // Software capture must read the entire window, not the letterboxed
        // viewport packed against its left edge. Touch must keep its mapping.
        {
            video::Display software({"software",960,540,false,true});
            top.fill(0xffff0000);bottom.fill(0xff00ff00);mask.fill(0);
            video::Frame screens{nullptr,top.data(),bottom.data(),mask.data(),false};
            software.present(screens);pixels=software.read_pixels();
            require(pixels.size()==960*540,"software full-window dimensions");
            require(pixels[10+10*960]==0xff000000&&pixels[950+10*960]==0xff000000,"software captures both letterboxes");
            require(pixels[480+135*960]==0xffff0000&&pixels[480+405*960]==0xff00ff00,"software captures LCDs at actual window positions");
            require(software.touch(480,405,x,y)&&x==128&&y==96,"software capture restores logical touch mapping");
            auto* second=SDL_GetWindowFromID(2);require(second,"software SDL window exists");
            SDL_SetWindowSize(second,320,720);SDL_PumpEvents();software.present(screens);pixels=software.read_pixels();
            require(pixels.size()==320*720&&pixels[160+60*320]==0xff000000,"software captures portrait letterboxing");
            require(pixels[160+240*320]==0xffff0000&&pixels[160+480*320]==0xff00ff00,"software portrait LCD positions");
            require(software.touch(160,480,x,y)&&x==128&&y==96,"software capture restores resized touch mapping");
            std::cout<<"Software full-window readback checks passed\n";
        }
        std::cout<<"GPU geometry, two LCDs, UI, texture and touch checks passed: "<<display.device()<<'\n';
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
    SDL_Quit();return 0;
}
