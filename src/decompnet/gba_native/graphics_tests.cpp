// Original CC0 GBA raw-hardware scenes. No game, BIOS, logo or SDK payload.
#include "video.hpp"
#include "anygba/system.hpp"
#include "native_idle.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>

static void half(std::vector<uint8_t>& data,unsigned at,unsigned value){data[at]=uint8_t(value);data[at+1]=uint8_t(value>>8);}
static std::vector<uint8_t> rgb(std::span<const uint16_t> frame){
    std::vector<uint8_t> out;for(auto c:frame)for(int s:{0,5,10}){unsigned v=(c>>s)&31;out.push_back(uint8_t((v<<3)|(v>>2)));}return out;
}
// Compare at the actual drawable size: Windows display scaling can make it
// differ from the requested logical window size. Include letterbox pixels.
static void compare(const gba_video::Display& display,const std::vector<uint8_t>& expected,unsigned variant){
    const int width=display.width(),height=display.height();
    const auto& actual=display.pixels();
    if(width<=0||height<=0||actual.size()!=size_t(width)*height*3)throw std::runtime_error("invalid GPU readback dimensions");
    int w=width,h=w*2/3;if(h>height){h=height;w=h*3/2;}
    if(w<=0||h<=0)throw std::runtime_error("invalid GPU viewport dimensions");
    const int left=(width-w)/2,top=height-(height-h)/2-h;
    for(int y=0;y<height;++y)for(int x=0;x<width;++x)for(int c=0;c<3;++c){
        unsigned wanted=0;
        if(x>=left&&x<left+w&&y>=top&&y<top+h){
            const int sx=int((int64_t(2*(x-left)+1)*240)/(2*w));
            const int sy=int((int64_t(2*(y-top)+1)*160)/(2*h));
            wanted=expected[(sy*240+sx)*3+c];
        }
        const auto got=actual[(size_t(y)*width+x)*3+c];
        if(got!=wanted)throw std::runtime_error("GPU mismatch variant "+std::to_string(variant)+" at "+std::to_string(x)+","+std::to_string(y)+" channel "+std::to_string(c)+" GPU="+std::to_string(got)+" reference="+std::to_string(wanted));
    }
}
int main(int argc,char** argv){try{
    if(argc!=1&&(argc!=3||std::string(argv[1])!="--report"))throw std::runtime_error("usage: gba_gpu_tests [--report NEW_FILE]");
    gba_video::Options options;options.renderer="opengl";options.width=240;options.height=160;options.readback=true;options.hidden=true;
    gba_video::Display display(options);
    int initial_width=0,initial_height=0,resized_width=0,resized_height=0,odd_width=0,odd_height=0;
    for(unsigned variant=0;variant<18;++variant){
        std::vector<uint8_t> rom(0x100);rom[0]=0xfe;rom[1]=0xff;rom[2]=0xff;rom[3]=0xea;
        anygba::Options runtime_options;runtime_options.log_misses=false;
        const auto program=original_idle_game(uint32_t(rom.size()));
        auto machine=std::make_unique<anygba::System>(rom,&program,runtime_options);
        auto& m=machine->memory();
        for(unsigned i=0;i<512;++i)half(m.palette,i*2,((i*3)&31)|(((i*5)&31)<<5)|(((i*7)&31)<<10));
        for(unsigned i=0;i<m.vram.size();++i)m.vram[i]=uint8_t(i*37+i/64);
        for(unsigned n=0;n<128;++n)half(m.oam,n*8,512);
        unsigned mode=variant%6;
        machine->io_write16(0,mode|0x1f40);
        for(unsigned bg=0;bg<4;++bg){
            machine->io_write16(8+2*bg,uint16_t(0x6000+((16+bg)<<8)+((bg&3)<<2)+(bg&1?128:0)+(bg&3)));
            machine->io_write16(16+4*bg,uint16_t(11+bg*17));machine->io_write16(18+4*bg,uint16_t(7+bg*13));
        }
        for(unsigned bg=0;bg<2;++bg){unsigned at=32+16*bg;
            machine->io_write16(at,224);machine->io_write16(at+2,64);
            machine->io_write16(at+4,uint16_t(-64));machine->io_write16(at+6,224);
            machine->io_write16(at+8,uint16_t(-4096));machine->io_write16(at+10,0x0fff);
            machine->io_write16(at+12,2048);machine->io_write16(at+14,0);
        }
        for(unsigned n=0;n<20;++n){
            unsigned a0=((n*17)&127)|(n%4==1?0x300:0)|(n%5==0?0x400:0)|(n%6==0?0x800:0)|(n%3==0?0x2000:0);
            unsigned a1=((n*23)&511)|((n&1)<<14)|(n%4==1?0:((n%3)<<12));
            half(m.oam,n*8,a0);half(m.oam,n*8+2,a1);half(m.oam,n*8+4,512+n*8+((n%4)<<10)+((n%16)<<12));
        }
        half(m.oam,6,256);half(m.oam,14,64);half(m.oam,22,uint16_t(-64));half(m.oam,30,256);
        if(variant>=6){
            machine->io_write16(0,uint16_t(mode|0xff50));
            machine->io_write16(64,(20<<8)|170);machine->io_write16(66,(100<<8)|220);
            machine->io_write16(68,(15<<8)|140);machine->io_write16(70,(40<<8)|155);
            machine->io_write16(72,0x3f17);machine->io_write16(74,0x2b3f);
            machine->io_write16(76,0x3232);
            for(unsigned bg=0;bg<4;++bg)machine->io_write16(8+2*bg,uint16_t(machine->io_read16(8+2*bg)|64));
        }
        machine->io_write16(80,uint16_t(0x3f3f|((variant%4)<<6)));machine->io_write16(82,0x080b);machine->io_write16(84,11);
        if(variant>=12)machine->io_write16(2,1);
        machine->mark_vram_written();
        gba_video::Scene scene;
        machine->on_line_rendered=[&](anygba::System& s,unsigned line){
            scene.capture(s,line);
            if(line==70){s.io_write16(16,80);half(s.memory().palette,6,0x7fff);s.memory().vram[1234]^=0xff;s.mark_vram_written();}
        };
        machine->on_vblank=[](anygba::System& s){s.stop();};machine->run();
        auto expected=rgb(machine->framebuffer());
        // The GPU must decode hardware state even when the supplied software picture is wrong.
        std::vector<uint16_t> unrelated(240*160,0x03e0);display.present(scene,unrelated);
        compare(display,expected,variant);
        if(!variant){initial_width=display.width();initial_height=display.height();}
        std::cout<<"passed GPU scene "<<variant<<"\n";
        if(variant==17){
            display.resize(480,320);display.present(scene,unrelated);compare(display,expected,variant);
            resized_width=display.width();resized_height=display.height();
            if(resized_width<=initial_width||resized_height<=initial_height)throw std::runtime_error("GPU drawable did not grow after resizing");
            display.resize(481,327);display.present(scene,unrelated);compare(display,expected,variant);
            odd_width=display.width();odd_height=display.height();
        }
    }
    if(argc==3){
        if(std::filesystem::exists(argv[2]))throw std::runtime_error("choose a new GPU report path");
        std::ofstream report(argv[2]);if(!report)throw std::runtime_error("cannot open GPU report");
        report<<"{\"schema\":\"decomp.wtf.gba-gpu-scenes/v1\",\"passed\":true,\"scenes\":18,\"renderer\":\"opengl\",\"device\":"<<std::quoted(display.device())
            <<",\"initial_drawable\":["<<initial_width<<','<<initial_height<<"],\"resized_drawable\":["<<resized_width<<','<<resized_height<<"],\"odd_drawable\":["<<odd_width<<','<<odd_height<<"],\"reference_picture_ignored\":true,\"resize_passed\":true}";
        report.close();if(!report)throw std::runtime_error("GPU report write failed");
    }
    std::cout<<"18 GPU/reference scenes and drawable resize passed on "<<display.device()<<"\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
