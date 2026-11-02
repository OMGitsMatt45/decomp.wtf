// SPDX-License-Identifier: MIT
#include "anygba/audio_interpolator.hpp"
#include "audio_settings.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool success,const char* message){if(!success)throw std::runtime_error(message);}
constexpr double pi=3.14159265358979323846,clock_rate=16777216.0;
double signal(std::uint64_t time,double frequency){return 90*std::cos(2*pi*frequency*time/clock_rate);}
std::int8_t value(std::uint64_t time,double frequency){return std::int8_t(std::lround(signal(time,frequency)));}
std::pair<double,double> measure(unsigned period,double frequency,bool reject){
 anygba::AudioInterpolator interpolation;
 std::uint64_t next=0;std::int8_t held=0;
 double original=0,enhanced=0;
 for(unsigned i=0;i<8192;++i){
  const auto at=std::uint64_t(i+1)*512;
  while(next<=at){held=value(next,frequency);interpolation.push(held,next);next+=period;}
  std::array<std::int8_t,8> future;for(unsigned j=0;j<8;++j)future[j]=value(next+j*period,frequency);
  const double target=reject?0:signal(at,frequency);
  if(i>128){original+=std::pow(held-target,2);enhanced+=std::pow(interpolation.sample(at,future,held)-target,2);}
 }
 return {std::sqrt(original/8063),std::sqrt(enhanced/8063)};
}
}
int main(int argc,char** argv){try{
 anygba::AudioInterpolator interpolation;
 std::array<std::int8_t,8> future;future.fill(37);
 check(interpolation.sample(512,future,-12)==-12,"startup must preserve held sample");
 for(unsigned n=0;n<12;++n)interpolation.push(37,std::uint64_t(n)*1254);
 for(unsigned n=0;n<=256;++n)check(std::abs(interpolation.sample(11*1254+n*1254/256,future,37)-37)<1e-9,"DC gain changed");
 check(interpolation.sample(15*1254,future,-12)==-12,"stopped clocks must not synthesize queued samples");
 interpolation.reset();check(interpolation.sample(12000,future,-12)==-12,"reset leaked interpolation history");
 interpolation.push(-20,100);interpolation.push(-20,200);interpolation.push(42,1000);
 check(interpolation.sample(1050,future,42)==42,"rate change must clear nonuniform history");
 const auto [held_error,clean_error]=measure(1254,800,false);
 check(clean_error<held_error*0.08,"in-band reconstruction error is excessive");
 const auto [held_alias,clean_alias]=measure(256,24000,true);
 check(clean_alias<held_alias*0.05,"above-Nyquist signal was not rejected");
 check(argc==2,"expected a scratch directory");
 const auto root=std::filesystem::path(argv[1]);std::filesystem::create_directories(root);
 const auto save=root/"preferences.sav";
 {std::ofstream file(save,std::ios::binary);file<<"untouched player save";}
 gba_frontend::AudioSettings settings;settings.load(save,false);
 bool notified=false;settings.changed=[&](bool v){notified=v;};settings.set(true,true);
 check(notified,"audio callback was not called");
 gba_frontend::AudioSettings loaded;loaded.load(save,false);check(loaded.enhanced,"audio setting did not persist");
 loaded.set(false,true);settings.load(save,true);check(!settings.enhanced,"atomic preference replacement failed");
 std::ifstream file(save);std::string data;std::getline(file,data);check(data=="untouched player save","audio settings modified the game save");
 std::cout<<"Band-limited audio passed: 800 Hz error "<<held_error<<" -> "<<clean_error
          <<"; 24 kHz alias RMS "<<held_alias<<" -> "<<clean_alias<<". Settings round-trip preserved the save.\n";
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
