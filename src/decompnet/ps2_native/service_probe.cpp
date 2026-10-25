// CC0 original service fixture. No game/BIOS data, window or audio device.
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "ps2_syscalls.h"
#include "ps2_stubs.h"
#include "runtime/ps2_pad_host.h"
#include "decomp_disc_files.hpp"
#include "spu2.h"
#include "ps2_iop_transport.h"
#include <array>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>

static void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
class OriginalPcm final:public ps2x::iop::lle::Spu2Host {
public:
 unsigned blocks=0;
 bool fetchAutoDma(int core,uint16_t *block) override {
  if(core!=1)return false;++blocks;
  for(unsigned n=0;n<256;++n){block[n]=8192;block[n+256]=4096;}
  return true;
 }
 void raiseSpuInterrupt() override {}
};
int main(int argc,char **argv){try{
 if(argc!=3)throw std::runtime_error("service fixture: ROOT write|read");
 const std::filesystem::path root=argv[1];
 auto runtime=std::make_unique<PS2Runtime>();require(runtime->memory().initialize(),"memory");
 auto &ctx=runtime->cpu();auto *ram=runtime->memory().getRDRAM();
 auto reg=[&](unsigned n,uint32_t v){ctx.r[n]=_mm_set_epi64x(0,v);};
 auto value=[&](){return static_cast<int32_t>(_mm_extract_epi32(ctx.r[2],0));};
 auto word=[&](unsigned a){uint32_t v;std::memcpy(&v,ram+a,4);return v;};
 auto paths=PS2Runtime::getIoPaths();paths.elfDirectory=root;paths.cdRoot=root/"local";paths.mcRoot=root/"cards/mc0";paths.cdImage=root/"disc.img";
 std::filesystem::create_directories(paths.cdRoot);PS2Runtime::setIoPaths(paths);
 const decomp_ps2::disc::Entry files[]={{"DATA.BIN",3,3000}};decomp_ps2::disc::mount(paths.cdImage,files);
 constexpr uint32_t name=0x200000,buffer=0x201000,stat=0x202000,cmd=0x203000,result=0x203004;
 ps2x::iop::RpcRequest request{};request.sid=0x80000593u;request.function=3;request.receive={stat,4};
 auto rpc=[&](){return PS2IopTransport::handleRpc(runtime.get(),ram,&ctx,request);};
 require(rpc().handled&&word(stat)==0x14,"CDVD RPC DVD medium");
 decomp_ps2::disc::mount(paths.cdImage,files,2048,0,0x12);
 require(rpc().handled&&word(stat)==0x12,"CDVD RPC CD medium");
 request.function=0x23;request.send={buffer,4};uint32_t priority=34;std::memcpy(ram+buffer,&priority,4);
 require(rpc().handled&&word(stat)==1&&decomp_ps2::disc::priority()==34,"CDVD command priority");
 priority=127;std::memcpy(ram+buffer,&priority,4);require(rpc().handled&&word(stat)==0&&decomp_ps2::disc::priority()==34,"invalid CDVD priority");
 request.receive={0x1fffffe,4};bool rejected=false;
 try{(void)rpc();}catch(const std::runtime_error&){rejected=true;}
 require(rejected,"CDVD reply bounds");
 std::strcpy(reinterpret_cast<char*>(ram+name),"cdrom0:\\DATA.BIN;1");
 reg(4,name);reg(5,stat);ps2_syscalls::fioGetstat(ram,&ctx,runtime.get());
 require(value()==0&&word(stat+8)==3000&&word(stat+36)==0,"indexed FIO stat");
 reg(4,name);reg(5,PS2_FIO_O_RDONLY);ps2_syscalls::fioOpen(ram,&ctx,runtime.get());const int fd=value();require(fd>=0,"read-only FIO open");
 std::memset(ram+buffer,0xa5,4000);reg(4,fd);reg(5,buffer);reg(6,4000);ps2_syscalls::fioRead(ram,&ctx,runtime.get());
 require(value()==3000&&ram[buffer+3000]==0xa5,"FIO bounded EOF");
 for(unsigned n=0;n<3000;++n)require(ram[buffer+n]==n%251,"FIO original bytes");
 reg(4,fd);reg(5,2993);reg(6,PS2_FIO_SEEK_SET);ps2_syscalls::fioLseek(ram,&ctx,runtime.get());require(value()==2993,"FIO seek");
 reg(4,fd);reg(5,buffer);reg(6,100);ps2_syscalls::fioRead(ram,&ctx,runtime.get());require(value()==7,"FIO tail read");
 reg(4,fd);ps2_syscalls::fioClose(ram,&ctx,runtime.get());require(value()==0,"FIO close");
 reg(4,name);reg(5,PS2_FIO_O_RDWR);ps2_syscalls::fioOpen(ram,&ctx,runtime.get());require(value()<0,"disc write must fail");
 reg(4,stat);reg(5,name);ps2_stubs::sceCdSearchFile(ram,&ctx,runtime.get());
 require(value()==1&&word(stat)==3&&word(stat+4)==3000,"original CD sector/size lookup");
 reg(4,3);reg(5,1);reg(6,buffer);reg(7,0);ps2_stubs::sceCdRead(ram,&ctx,runtime.get());require(value()==1,"CD read");
 for(unsigned n=0;n<2048;++n)require(ram[buffer+n]==n%251,"CD sector bytes");
 ps2PadPublishHostState(0,1u<<14,0x10203040);PSPadBackend pad;uint8_t report[32];
 require(pad.readState(0,0,report,sizeof(report))&&!(report[3]&0x40)&&report[4]==0x10&&report[7]==0x40,"published pad edge/axes");
 require(pad.readState(0,0,report,sizeof(report))&&(report[3]&0x40),"pad edge must be consumed once");
 OriginalPcm pcm;ps2x::iop::lle::Spu2 spu(pcm);
 // Original register program: core 1 AutoDMA, dry PCM gates and fixed stereo
 // master/input gains. The expected samples follow two integer gain stages.
 spu.write(0x598,0x00c0);spu.write(0x5b0,2);
 spu.write(0x788,0x3fff);spu.write(0x78a,0x3fff);spu.write(0x794,0x7fff);spu.write(0x796,0x7fff);
 for(unsigned n=0;n<1024;++n){int16_t left=0,right=0;spu.tick(left,right);require(left==8190&&right==4094,"SPU2 original stereo PCM gains/refill");}
 require(pcm.blocks>=4,"SPU2 AutoDMA refill");
 ps2_stubs::sceMcInit(ram,&ctx,runtime.get());
 auto sync=[&](){reg(4,0);reg(5,cmd);reg(6,result);ps2_stubs::sceMcSync(ram,&ctx,runtime.get());require(value()==1,"memory card command completion");return static_cast<int32_t>(word(result));};
 const bool writing=std::string(argv[2])=="write";const char payload[]="original PS2 save";
 std::strcpy(reinterpret_cast<char*>(ram+name),"SAVE.BIN");
 reg(4,0);reg(5,1);reg(6,name);reg(7,writing?(PS2_FIO_O_RDWR|PS2_FIO_O_CREAT|PS2_FIO_O_TRUNC):PS2_FIO_O_RDONLY);
 ps2_stubs::sceMcOpen(ram,&ctx,runtime.get());const int card=sync();require(card>=0,"memory card open");
 reg(4,card);reg(5,buffer);reg(6,sizeof(payload));
 if(writing){std::memcpy(ram+buffer,payload,sizeof(payload));ps2_stubs::sceMcWrite(ram,&ctx,runtime.get());}
 else{std::memset(ram+buffer,0,sizeof(payload));ps2_stubs::sceMcRead(ram,&ctx,runtime.get());}
 require(sync()==sizeof(payload),"memory card read/write size");
 if(!writing)require(std::memcmp(ram+buffer,payload,sizeof(payload))==0,"memory card reload bytes");
 reg(4,card);ps2_stubs::sceMcClose(ram,&ctx,runtime.get());require(sync()==0,"memory card close");
 std::cout<<"{\"filesystem\":true,\"cd\":true,\"cdvd_rpc\":true,\"input\":true,\"spu2_pcm_samples\":1024,\"save\":"<<(writing?"\"write\"":"\"reload\"")<<"}\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
