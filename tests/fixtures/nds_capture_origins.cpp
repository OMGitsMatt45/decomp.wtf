// Original display-capture fixture. No retail game code or assets.
#include "dsr/gpu2d.h"
#include "dsr/gpu3d.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
namespace {
std::array<std::array<std::uint32_t,256>,192> picture;
std::uint64_t generation=7;
constexpr std::uint64_t known=1ull<<32,invalid=1ull<<33;
unsigned checks=0;
void check(bool ok,const char* text){++checks;if(!ok)throw std::runtime_error(text);}
std::uint64_t tag(unsigned x,unsigned y,unsigned g=7){return(std::uint64_t(g)<<16)|(y*256+x+1);}
void lines(dsr::Gpu2D& gpu){for(int y=0;y<192;++y)gpu.render_line(y);}
void identity(dsr::Gpu2D& gpu,unsigned base=0x04000000){gpu.io_write(base+0x20,256,16);gpu.io_write(base+0x22,0,16);gpu.io_write(base+0x24,0,16);gpu.io_write(base+0x26,256,16);gpu.io_write(base+0x28,0,32);gpu.io_write(base+0x2c,0,32);}
void bitmap(dsr::Gpu2D& gpu,unsigned base=0x04000000){gpu.io_write(base,0x10405,32);gpu.io_write(base+0xc,0x4084,16);identity(gpu,base);}
void capture(dsr::Gpu2D& gpu,unsigned bank,unsigned mode=0,unsigned weights=16){gpu.io_write(0x04000240+bank,0x80,8);gpu.io_write(0x04000064,0x80000000|(1<<24)|(3<<20)|(bank<<16)|(mode<<29)|weights,32);lines(gpu);gpu.vblank_start();}
}
namespace dsr {
Gpu3D::Gpu3D():impl_(nullptr){}
Gpu3D::~Gpu3D()=default;
const std::uint32_t* Gpu3D::line(int y)const{return y>=0&&y<192?picture[y].data():nullptr;}
std::uint64_t Gpu3D::render_serial()const{return generation;}
}
int main(){try{
 for(unsigned y=0;y<192;++y)for(unsigned x=0;x<256;++x)picture[y][x]=(31u<<24)|((x&31)*2+1)|(((y&31)*2+1)<<6);
 dsr::Gpu3D three;dsr::Gpu2D gpu;gpu.attach_gpu3d(&three);unsigned remaps=0;gpu.on_vram_remap=[&]{++remaps;};
 check(!gpu.screen_top_origins()&&!gpu.screen_bottom_origins(),"tracking defaults off");gpu.set_capture_origin_tracking(true);check(remaps==1,"tracking invalidates cached CPU/DMA pages");
 gpu.io_write(0x04000304,0x820f,16);gpu.io_write(0x04000000,0x10108,32);capture(gpu,0);
 gpu.io_write(0x04000240,0x81,8);bitmap(gpu);generation=8;lines(gpu);
 const unsigned at=10*256+5;check(gpu.screen_top_origins()[at]==tag(5,10),"bitmap retains previous capture generation and coordinates");check(gpu.screen_top_foreground()[at]==known,"captured 3D is transparent in native foreground");check(gpu.three_d_mask()[at]==0,"captured bitmap is separate from live BG0 mask");
 auto retained=gpu.capture_origin_generations();check(retained==std::vector<std::uint64_t>{7},"retained generations include captured VRAM history");
 gpu.io_write(0x04000050,0x2044,16);gpu.io_write(0x04000052,8|(8<<8),16);lines(gpu);check(gpu.screen_top_origins()[at+1]==0,"real 2D alpha blending stays native");
 gpu.io_write(0x04000052,16,16);lines(gpu);check(gpu.screen_top_origins()[at+1]==tag(6,10),"identity 2D blend preserves captured origin");gpu.io_write(0x04000050,0,16);
 gpu.io_write(0x04000000,0x10108,32);gpu.io_write(0x04000050,0x2000,16);lines(gpu);check(gpu.screen_top_origins()[at+1]==tag(6,10,8),"opaque live 3D retains provenance over a second target");
 const auto original_pixel=picture[10][6];picture[10][6]=(original_pixel&0xffffff)|(16u<<24);lines(gpu);check(gpu.screen_top_origins()[at+1]==0,"partial live 3D blend remains native");picture[10][6]=original_pixel;
 gpu.io_write(0x04000050,0,16);bitmap(gpu);lines(gpu);
 const auto color=gpu.screen_top()[at];check(color==0xff295200,"observed metadata does not change captured RGB5 pixels");check(!gpu.arm9_vram_page(0x6000000),"observed CPU writes use invalidating slow path");
 gpu.arm9_write(0x6000000+at*2,gpu.arm9_read(0x6000000+at*2,16),8);lines(gpu);check(gpu.screen_top_origins()[at]==tag(5,10),"ignored VRAM byte write retains origin");
 gpu.arm9_write(0x6000000+at*2,gpu.arm9_read(0x6000000+at*2,16),16);lines(gpu);check(gpu.screen_top_origins()[at]==0&&gpu.screen_top_origins()[at+1]==tag(6,10),"same-value CPU write invalidates exactly its texel");check(gpu.screen_top()[at]==color,"origin invalidation is observational");check(gpu.screen_top_foreground()[at]==(known|color),"CPU writes become native foreground without inventing 3D");
 gpu.io_write(0x0400006c,0x4001,16);lines(gpu);check(gpu.screen_top_origins()[at+1]==0,"master brightness stays native");check(gpu.screen_top_foreground()[at+1]&invalid,"unsupported master effects are labelled");gpu.io_write(0x0400006c,0,16);
 gpu.io_write(0x04000028,3*256,32);gpu.io_write(0x0400002c,4*256,32);lines(gpu);check(gpu.screen_top_origins()[at]==tag(8,14),"affine scrolling retains exact source location");
 gpu.io_write(0x04000020,0,16);gpu.io_write(0x04000022,std::uint16_t(-256),16);gpu.io_write(0x04000024,256,16);gpu.io_write(0x04000026,0,16);gpu.io_write(0x04000028,255*256,32);gpu.io_write(0x0400002c,0,32);lines(gpu);check(gpu.screen_top_origins()[10*256+20]==tag(245,20),"rotated bitmap retains source coordinates");identity(gpu);
 // A real text layer must occlude the captured image, without losing its neighbours.
 gpu.io_write(0x04000000,0x10505,32);gpu.io_write(0x04000008,0x1f18,16);gpu.io_write(0x0400000c,0x4085,16);
 for(unsigned off=0;off<0x800;off+=2)gpu.arm9_write(0x600f800+off,0,16);
 gpu.arm9_write(0x600f800,1,16);gpu.arm9_write(0x6018020,0x11111111,32);gpu.arm9_write(0x5000002,31,16);lines(gpu);
 check(gpu.screen_top_origins()[0]==0&&gpu.screen_top()[0]==0xffff0000,"opaque text overlay keeps original pixels");check(gpu.screen_top_origins()[8]==tag(8,0),"text does not hide adjacent captured 3D");
 check(gpu.screen_top_foreground()[0]==(known|0xffff0000U),"opaque text remains native foreground");
 check(gpu.screen_top_foreground()[8]==known,"transparent text texel keeps captured scenery separate");
 gpu.io_write(0x04000050,0x441,16);gpu.io_write(0x04000052,10|(5<<8),16);lines(gpu);
 check(gpu.screen_top_foreground()[0]==(known|0xaf9f0000U),"unequal DS alpha weights include black opacity");
 gpu.io_write(0x04000052,16,16);lines(gpu);check(gpu.screen_top_foreground()[0]==(known|0xffff0000U),"pure-weight text foreground remains exact");
 gpu.io_write(0x04000052,16|(16<<8),16);lines(gpu);check(gpu.screen_top_foreground()[0]&invalid,"additive alpha requiring negative opacity is guarded");
 gpu.io_write(0x04000050,0,16);
 // LCDC capture sources must be mapped as LCDC; metadata survives mapping changes.
 gpu.io_write(0x04000240,0x80,8);gpu.io_write(0x04000000,2<<16,32);lines(gpu);check(gpu.screen_top_origins()[at+1]==tag(6,10),"LCDC display keeps captured origin");
 capture(gpu,1,1);gpu.io_write(0x04000240,0,8);gpu.io_write(0x04000241,0x81,8);bitmap(gpu);lines(gpu);check(gpu.screen_top_origins()[at+1]==tag(6,10),"VRAM source-B copy keeps old generation");check(gpu.screen_top_foreground()[at+1]==known,"VRAM copies preserve transparent native foreground");
 // Overlapping mappings OR their bytes; a unique origin cannot be inferred.
 gpu.io_write(0x04000240,0x81,8);lines(gpu);check(gpu.screen_top_origins()[at+1]==0,"overlapping banks reject ambiguous provenance");gpu.io_write(0x04000240,0,8);
 // Blended captures remain native; a full-weight A capture may retain metadata.
 gpu.io_write(0x04000000,0x10108,32);capture(gpu,2,2,8|(8<<8));gpu.io_write(0x04000241,0,8);gpu.io_write(0x04000242,0x84,8);bitmap(gpu,0x04001000);lines(gpu);
 check(gpu.screen_bottom_origins()[at+1]==0,"capture blending rejects false pure-3D origin");
 capture(gpu,2,2,16);gpu.io_write(0x04000242,0x84,8);lines(gpu);check(gpu.screen_bottom_origins()[at+1]==tag(6,10,8),"pure-weight capture survives engine-B mapping");
 retained=gpu.capture_origin_generations();check(std::find(retained.begin(),retained.end(),7)!=retained.end()&&std::find(retained.begin(),retained.end(),8)!=retained.end(),"current and older captured rasters remain referenced");
 gpu.io_write(0x04000242,0x82,8);check(!gpu.arm7_vram_page(0x6000000),"ARM7 direct writes also invalidate origins");gpu.arm7_write(0x6000000+(at+1)*2,0xffff,16);gpu.io_write(0x04000242,0x84,8);lines(gpu);check(gpu.screen_bottom_origins()[at+1]==0,"ARM7 write clears source tag");
 gpu.io_write(0x04000304,0x020f,16);lines(gpu);check(gpu.screen_top_origins()[at+2]==tag(7,10,8),"LCD swap routes engine-B provenance to top screen");
 gpu.set_capture_origin_tracking(false);check(gpu.capture_origin_generations().empty(),"disabled tracking exposes no retained rasters");check(!gpu.screen_top_foreground()&&!gpu.screen_bottom_foreground(),"disabled metadata has no foreground plane");check(!gpu.screen_top_origins()&&gpu.arm9_vram_page(0x6200000),"disable restores original VRAM fast path");gpu.set_capture_origin_tracking(true);lines(gpu);check(gpu.screen_top_origins()[at+2]==0,"enabling cannot invent history for existing bitmap pixels");gpu.reset();check(gpu.screen_top_origins()[0]==0,"reset clears source history");check(gpu.screen_top_foreground()[0]==0,"reset cannot reuse stale foreground");
 // Real capture history: an additive source-B is invalid, but its zero
 // coefficient must not contaminate a later pure-A capture.
 {dsr::Gpu2D other;other.attach_gpu3d(&three);other.set_capture_origin_tracking(true);
  other.io_write(0x04000304,0x820f,16);other.io_write(0x04000240,0x80,8);
  other.arm9_write(0x06800000+at*2,0x8000,16);other.io_write(0x04000000,2<<16,32);
  capture(other,1,2,16|(16<<8));other.io_write(0x04000000,(2<<16)|(1<<18),32);lines(other);
  check(other.screen_top_foreground()[at]&invalid,"additive captured background is labelled invalid");
  capture(other,2,2,16);other.io_write(0x04000240,0,8);other.io_write(0x04000241,0,8);other.io_write(0x04000242,0x81,8);bitmap(other);lines(other);
  check(other.screen_top_foreground()[at]==known,"zero-weight invalid capture source is ignored");
 }
 // A captured world may be displayed as bitmap OBJ on either engine,
 // alternating with a bitmap BG on the other LCD. It is still scene data.
 for(bool main:{true,false}) {
  dsr::Gpu2D objects;objects.attach_gpu3d(&three);objects.set_capture_origin_tracking(true);
  objects.io_write(0x04000304,0x820f,16);const unsigned bank=main?0:3,engine=main?0x04000000:0x04001000;
  const unsigned oam=main?0x07000000:0x07000400,vram=main?0x06400000:0x06600000;
  for(unsigned i=0;i<128;++i)objects.arm9_write(oam+i*8,0x0200,16);
  capture(objects,bank);objects.io_write(0x04000240+bank,main?0x82:0x84,8);
  objects.io_write(engine,0x11020,32);objects.io_write(engine+0x50,1u<<13,16);
  objects.arm9_write(oam,0x0c00,16);objects.arm9_write(oam+2,0xc000,16);objects.arm9_write(oam+4,0xf000,16);
  auto source=[&]{return main?objects.screen_top_origins():objects.screen_bottom_origins();};
  auto fg=[&]{return main?objects.screen_top_foreground():objects.screen_bottom_foreground();};
  lines(objects);check(source()[at]==tag(5,10,8),"bitmap OBJ keeps full-alpha captured source identity on either engine");
  check(fg()[at]==known,"bitmap OBJ captured scenery does not become a duplicate native foreground");
  const auto native=main?objects.screen_top()[at]:objects.screen_bottom()[at];
  objects.arm9_write(oam+2,0xd000,16);lines(objects);check(source()[at]==tag(58,10,8),"flipped captured OBJ tracks exact source texel");
  objects.arm9_write(oam+2,0xc000,16);objects.arm9_write(oam,0x0d00,16);
  objects.arm9_write(oam+6,256,16);objects.arm9_write(oam+14,0,16);objects.arm9_write(oam+22,0,16);objects.arm9_write(oam+30,256,16);
  lines(objects);check(source()[at]==tag(5,10,8),"affine captured OBJ retains source metadata");
  objects.arm9_write(oam,0x1c00,16);objects.io_write(engine+0x4c,(3u<<8)|(2u<<12),16);lines(objects);
  check(source()[at]==tag(4,9,8),"OBJ mosaic copies the selected captured texel and its provenance");
  objects.arm9_write(oam,0x0c00,16);objects.io_write(engine+0x4c,0,16);
  objects.arm9_write(oam+4,0x7000,16);lines(objects);check(source()[at]==0,"partial bitmap OBJ alpha is not a pure captured-scene origin");
  objects.arm9_write(oam+4,0xf000,16);lines(objects);check(source()[at]==tag(5,10,8),"full-alpha OBJ restores pure origin");
  objects.arm9_write(vram+at*2,objects.arm9_read(vram+at*2,16),16);lines(objects);
  check(source()[at]==0&&source()[at+1]==tag(6,10,8),"CPU write invalidates exactly one bitmap OBJ source texel");
  check(fg()[at]==(known|native),"invalidated OBJ texel becomes ordinary native foreground");
  objects.arm9_write(vram+at*2,0,16);lines(objects);check(source()[at]==0&&fg()[at]==known,"transparent bitmap OBJ does not retain a stale captured texel");
  if(main){objects.io_write(0x04000241,0x82,8);lines(objects);check(source()[at+1]==0,"OR-mapped OBJ banks reject ambiguous captured origins");}
  objects.set_capture_origin_tracking(false);lines(objects);check(!objects.screen_top_origins()&&!objects.screen_bottom_foreground(),"bitmap OBJ tracking remains optional");
 }
 std::cout<<checks<<" original captured-3D provenance checks passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
