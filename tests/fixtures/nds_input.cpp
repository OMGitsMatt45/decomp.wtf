// Original fixture for combining scripted DS touch input with live pointer input.
#include "input.hpp"
#include <stdexcept>
#include <iostream>
int main() {
    dsr::InputState scripted;
    scripted.buttons=1;scripted.pen_down=true;scripted.pen_x=112;scripted.pen_y=88;
    ds_host::merge_live_touch(scripted,false,0,0);
    if(!scripted.pen_down||scripted.pen_x!=112||scripted.pen_y!=88||scripted.buttons!=1)
        throw std::runtime_error("idle pointer erased scripted touch");
    ds_host::merge_live_touch(scripted,true,220,144);
    if(!scripted.pen_down||scripted.pen_x!=220||scripted.pen_y!=144||scripted.buttons!=1)
        throw std::runtime_error("live pointer did not override touch");
    dsr::InputState idle;
    ds_host::merge_live_touch(idle,false,0,0);
    if(idle.pen_down)throw std::runtime_error("idle input created a touch");
    ds_host::merge_live_touch(idle,true,0,191);
    if(!idle.pen_down||idle.pen_x!=0||idle.pen_y!=191)
        throw std::runtime_error("live touch was lost");
    std::cout<<"Scripted and live touch merge checks passed\n";
}
