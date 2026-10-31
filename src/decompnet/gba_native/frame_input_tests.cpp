// SPDX-License-Identifier: CC0-1.0
// Events arriving during real host work must reach the next emulated frame.
#include "frame_input.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Host {
    unsigned time=0,press=8,release=100,close=100;
    void pace(){time=16;}
    bool poll(uint16_t& keys,bool* settings,bool* button){
        keys=time>=press&&time<release?16:0;
        *settings=false;*button=false;
        return time<close;
    }
};
}
int main(){
    try {
        Host held;
        auto a=gba_frontend::present_and_sample(held,[&]{held.time=6;},true);
        require(a.keys==16,"press during frame wait was deferred until another frame");
        require(a.running,"normal input stopped playback");
        Host released;released.press=0;released.release=4;
        auto b=gba_frontend::present_and_sample(released,[&]{released.time=6;},true);
        require(b.keys==0,"release during rendering left movement held for another frame");
        Host closing;closing.close=12;
        auto c=gba_frontend::present_and_sample(closing,[&]{closing.time=6;},true);
        require(!c.running,"close during frame wait ran another emulated frame");
        Host unpaced;unpaced.press=4;
        auto d=gba_frontend::present_and_sample(unpaced,[&]{unpaced.time=6;},false);
        require(unpaced.time==6&&d.keys==16,"unpaced playback waited or sampled stale controls");
        std::cout<<"Live presses, releases and close events reach the next frame; unpaced sampling passed.\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
