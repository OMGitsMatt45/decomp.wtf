// SPDX-License-Identifier: CC0-1.0. Original host-audio qualification.
#include <dsr/spu.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
struct Bus {
    std::array<uint8_t,65536> memory{};
    std::vector<std::array<uint32_t,3>> trace;
    void bind(dsr::Spu& spu) {
        spu.read8=[&](uint32_t a){auto v=memory[a%memory.size()];trace.push_back({0,a,v});return v;};
        spu.write8=[&](uint32_t a,uint8_t v){trace.push_back({1,a,v});memory[a%memory.size()]=v;};
    }
    void pcm(unsigned address,std::initializer_list<int16_t> samples) {
        for(auto sample:samples){memory[address++]=uint8_t(sample);memory[address++]=uint8_t(uint16_t(sample)>>8);}
    }
};
void channel(dsr::Spu& spu,unsigned n,uint32_t address,unsigned period,unsigned format,unsigned words,unsigned extra=0) {
    const unsigned reg=0x04000400+16*n;
    spu.io_write(reg+4,address,32);spu.io_write(reg+8,65536-period/2,16);
    spu.io_write(reg+12,words,32);spu.io_write(reg,0x8000007f|(1u<<27)|(format<<29)|extra,32);
}
void master(dsr::Spu& spu){spu.io_write(0x04000500,0x807f,16);}
std::vector<int16_t> render(dsr::Spu& spu,unsigned frames) {
    spu.run(int64_t(frames)*dsr::Spu::kTicksPerSample);
    std::vector<int16_t> samples(frames*2);require(spu.drain(samples.data(),frames)==frames,"unchanged audio frame count");return samples;
}
double energy(const std::vector<int16_t>& samples,unsigned bin) {
    std::complex<double> value{};constexpr unsigned n=2048;
    for(unsigned i=0;i<n;++i){const double phase=-6.283185307179586*bin*i/n;value+=double(samples[(i+64)*2])*std::complex<double>(std::cos(phase),std::sin(phase));}
    return std::norm(value);
}
int main() {
    try {
        {
            dsr::Spu old,clean;Bus a,b;a.pcm(256,{1001,1001,1001,1001});b.memory=a.memory;a.bind(old);b.bind(clean);
            clean.set_output_quality(dsr::Spu::OutputQuality::Clean);
            for(auto* s:{&old,&clean}){master(*s);channel(*s,0,256,512,1,2);}
            auto hardware=render(old,16),precise=render(clean,16);
            require(hardware[30]==960&&precise[30]==1001&&precise[31]==0,"retain actual low sample bits without gain or stereo changes");
            require(a.trace==b.trace,"cleanup does not read ahead");
            clean.reset();master(clean);channel(clean,0,256,512,1,2);
            require(render(clean,16)[30]==1001,"host quality survives hardware reset");
        }
        {
            dsr::Spu old,clean;Bus a,b;a.pcm(256,{0,12000,0,-12000});b.memory=a.memory;a.bind(old);b.bind(clean);
            clean.set_output_quality(dsr::Spu::OutputQuality::Clean);
            for(auto* s:{&old,&clean}){master(*s);channel(*s,0,256,2048,1,2);}
            auto hardware=render(old,4096),interpolated=render(clean,4096);
            const auto before=energy(hardware,768)/energy(hardware,256),after=energy(interpolated,768)/energy(interpolated,256);
            require(after<before*.5,"sample interpolation reduces the high-frequency spectral image");
            require(energy(interpolated,256)>energy(interpolated,255)*100,"tone frequency is unchanged");
            require(a.trace==b.trace,"interpolation consumes exactly the hardware sample reads");
            std::cout<<"Spectral image/fundamental power: "<<before<<" -> "<<after<<'\n';
        }
        for(int value:{32767,-32768,0})for(unsigned bias:{0u,512u,1023u}) {
            dsr::Spu clean;Bus bus;bus.pcm(256,{int16_t(value),int16_t(value),int16_t(value),int16_t(value)});bus.bind(clean);
            clean.set_output_quality(dsr::Spu::OutputQuality::Clean);master(clean);clean.io_write(0x04000504,bias,16);
            for(unsigned n=0;n<16;++n)channel(clean,n,256,512,1,2);
            auto samples=render(clean,16);const auto expected=std::clamp(std::clamp(value*16+int(bias*64),0,65535)-int(bias*64),-32768,32767);
            require(samples[30]==expected&&samples[31]==0,"saturation, bias and silence have no wraparound or added gain");
            clean.io_write(0x04000500,0,16);require(render(clean,4)[6]==0,"disabled master remains silent");
        }
        {
            dsr::Spu old,clean;Bus a,b;
            for(unsigned i=0;i<a.memory.size();++i)a.memory[i]=uint8_t(i*17+i/7);
            a.memory[1026]=24;b.memory=a.memory;a.bind(old);b.bind(clean);
            clean.set_output_quality(dsr::Spu::OutputQuality::Clean);
            for(auto* s:{&old,&clean}) {
                master(*s);channel(*s,0,256,1500,0,8);channel(*s,2,1024,900,2,8);
                channel(*s,3,0x3000,1600,1,16);channel(*s,8,0,256,3,0,3u<<24);channel(*s,14,0,512,3,0);
                s->io_write(0x04000418,0xfe80,16);
                s->io_write(0x04000510,0x3000,32);s->io_write(0x04000514,32,32);s->io_write(0x04000508,0x80,8);
                s->io_write(0x04000518,0x3400,32);s->io_write(0x0400051c,4,32);s->io_write(0x04000509,0x8e,8);
            }
            const unsigned chunks[]={1,9,2048,333,900,17};
            for(unsigned i=0;i<600;++i) {
                if(i==150)for(auto* s:{&old,&clean})s->io_write(0x04000400,93,8);
                if(i==250)for(auto* s:{&old,&clean})s->set_channel_muted(2,true);
                if(i==350)for(auto* s:{&old,&clean})s->io_write(0x04000408,0xff11,16);
                old.run(chunks[i%6]);clean.run(chunks[i%6]);
            }
            require(a.trace==b.trace&&a.memory==b.memory,"capture/reverb feedback preserves every ordered guest bus read and write");
            for(unsigned a=0x04000400;a<=0x0400051c;a+=4)require(old.io_read(a,32)==clean.io_read(a,32),"guest sound registers are unchanged");
            const auto x=old.debug_state(),y=clean.debug_state();
            for(unsigned n=0;n<16;++n)require(x.channels[n].sample_position==y.channels[n].sample_position&&x.channels[n].current_sample==y.channels[n].current_sample&&x.channels[n].busy==y.channels[n].busy,"decoders and channel completion times are unchanged");
            std::array<int16_t,4096> p{},q{};require(old.drain(p.data(),2048)==clean.drain(q.data(),2048),"capture modes preserve output frame counts");
        }
        for(unsigned n:{8u,14u}) {
            dsr::Spu old,clean;master(old);master(clean);clean.set_output_quality(dsr::Spu::OutputQuality::Clean);
            channel(old,n,0,640,3,0,3u<<24);channel(clean,n,0,640,3,0,3u<<24);
            auto a=render(old,256),b=render(clean,256);
            for(unsigned i=0;i<a.size();++i)require((int(b[i])&~63)==a[i],"PSG/noise waveforms keep their hardware phase and shape");
        }
        std::cout<<"Audio precision, interpolation, clipping, PSG/noise and guest capture isolation checks passed\n";
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
