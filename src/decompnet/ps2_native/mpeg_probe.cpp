// CC0 original MPEG-2 video fixture: authored pixels, no game/movie/BIOS data.
#include "ps2_runtime.h"
#include "ps2_stubs.h"
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/imgutils.h>
}
static void require(bool value,const char *message){if(!value)throw std::runtime_error(message);}
struct Encoder {
    AVCodecContext *context=nullptr;AVFrame *frame=nullptr;AVPacket *packet=nullptr;
    ~Encoder(){av_packet_free(&packet);av_frame_free(&frame);avcodec_free_context(&context);}
};
static std::vector<uint8_t> original_video(){
    Encoder e;const AVCodec *codec=avcodec_find_encoder(AV_CODEC_ID_MPEG2VIDEO);require(codec,"MPEG-2 encoder unavailable");
    e.context=avcodec_alloc_context3(codec);e.frame=av_frame_alloc();e.packet=av_packet_alloc();
    require(e.context&&e.frame&&e.packet,"MPEG fixture allocation");
    e.context->width=32;e.context->height=16;e.context->pix_fmt=AV_PIX_FMT_YUV420P;
    e.context->time_base={1,25};e.context->framerate={25,1};e.context->gop_size=1;e.context->max_b_frames=0;e.context->bit_rate=400000;
    require(avcodec_open2(e.context,codec,nullptr)>=0,"MPEG fixture encoder initialization");
    e.frame->format=e.context->pix_fmt;e.frame->width=32;e.frame->height=16;
    require(av_frame_get_buffer(e.frame,32)>=0,"MPEG fixture picture allocation");
    std::vector<uint8_t> bytes;
    auto drain=[&](){int status;while((status=avcodec_receive_packet(e.context,e.packet))==0){
        bytes.insert(bytes.end(),e.packet->data,e.packet->data+e.packet->size);av_packet_unref(e.packet);}
        require(status==AVERROR(EAGAIN)||status==AVERROR_EOF,"MPEG fixture packet encoding");};
    for(int n=0;n<3;++n){
        require(av_frame_make_writable(e.frame)>=0,"MPEG fixture writable picture");
        for(int plane=0;plane<3;++plane)for(int y=0;y<(plane?8:16);++y)
            std::fill_n(e.frame->data[plane]+y*e.frame->linesize[plane],plane?16:32,plane==0?81:(plane==1?90:240));
        e.frame->pts=n;require(avcodec_send_frame(e.context,e.frame)>=0,"MPEG fixture frame submission");drain();
    }
    require(avcodec_send_frame(e.context,nullptr)>=0,"MPEG fixture encoder drain");drain();
    bytes.insert(bytes.end(),{0,0,1,0xb7});return bytes;
}
int main(){try{
    const auto video=original_video();auto runtime=std::make_unique<PS2Runtime>();
    require(runtime->memory().initialize(),"guest RAM initialization");
    runtime->configureGuestHeap(0x240000,0x250000);
    auto *ram=runtime->memory().getRDRAM();auto &ctx=runtime->cpu();
    auto reg=[&](unsigned n,uint32_t value){ctx.r[n]=_mm_set_epi64x(0,value);};
    auto word=[&](unsigned at){uint32_t value;std::memcpy(&value,ram+at,4);return value;};
    constexpr uint32_t object=0x210000,work=0x220000,input=0x260000,picture=0x270000;
    std::vector<uint8_t> unrelated(ram+0x100000,ram+0x200000);
    ps2_stubs::sceMpegInit(ram,&ctx,runtime.get());
    for(unsigned mode=0;mode<6;++mode){
    reg(4,object);reg(5,work);reg(6,8192);ps2_stubs::sceMpegCreate(ram,&ctx,runtime.get());
    require(word(object+0x40)==work,"MPEG work-buffer identity");
    std::memcpy(ram+input,video.data(),video.size());reg(4,object);reg(5,input);reg(6,video.size());
    ps2_stubs::sceMpegAddBs(ram,&ctx,runtime.get());
    require(static_cast<uint32_t>(_mm_extract_epi32(ctx.r[2],0))==video.size(),"MPEG bitstream consumption");
    std::memset(ram+picture,0xa5,8192);
    reg(4,object);reg(5,mode>=4?0x1fffffcu:picture);reg(6,mode==2?3u:(mode==3?1u:2u));reg(7,mode==2?2u:0u);
    bool rejected=false;
    try{
        if(mode==0||mode==5)ps2_stubs::sceMpegGetPicture(ram,&ctx,runtime.get());
        else if(mode==2)ps2_stubs::sceMpegGetPictureRAW8xy(ram,&ctx,runtime.get());
        else ps2_stubs::sceMpegGetPictureRAW8(ram,&ctx,runtime.get());
    }catch(const std::runtime_error&){rejected=true;}
    require(rejected==(mode>=3),"MPEG RAW8 invalid buffer rejection");
    require(word(object)==32&&word(object+4)==16&&word(object+8)==0,"decoded MPEG dimensions/picture readiness");
    if(mode<3)require(word(work+0xe4)==(mode==2?6u:2u),"MPEG output macroblock capacity metadata");
    if(mode==0){
    for(unsigned n=0;n<32*16;++n){const auto *p=ram+picture+4*n;
        require(p[0]>=248&&p[1]<=5&&p[2]<=5&&p[3]==0x80,"decoded MPEG original red pixels/GS alpha");}
    }else if(mode<3){
        for(unsigned column=0;column<2;++column)for(unsigned n=0;n<384;++n){
            const unsigned expected=n<256?81:(n<320?90:240);
            const int actual=ram[picture+column*(mode==2?768:384)+n];
            require(std::abs(actual-int(expected))<=2,"decoded RAW8 Y/Cb/Cr planes and macroblock stride");
        }
        for(unsigned n=0;n<8192;++n)if(n>=384&&(mode==1?n>=768:(n<768||n>=1152)))
            require(ram[picture+n]==0xa5,"RAW8 padding and tail canaries");
    }else for(unsigned n=0;n<8192;++n)require(ram[picture+n]==0xa5,"invalid RAW8 buffer caused partial writes");
    reg(4,object);ps2_stubs::sceMpegClearRefBuff(ram,&ctx,runtime.get());
    ps2_stubs::sceMpegReset(ram,&ctx,runtime.get());ps2_stubs::sceMpegDelete(ram,&ctx,runtime.get());
    require(std::equal(unrelated.begin(),unrelated.end(),ram+0x100000),"MPEG services changed unrelated guest code/data");
    }
    std::cout<<"{\"mpeg2\":true,\"raw8\":true,\"raw8xy\":true,\"guarded_buffers\":true,\"decoded_pixels\":512,\"preserved_guest_bytes\":1048576,\"encoded_bytes\":"<<video.size()<<"}\n";
    return 0;
}catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}}
