// SPDX-License-Identifier: MIT
#pragma once
#include <dsr/session.h>

namespace ds_host {
// A live pointer augments this frame's scripted input only while touching an LCD.
inline void merge_live_touch(dsr::InputState& input,bool touching,int x,int y) {
    if(!touching)return;
    input.pen_down=true;
    input.pen_x=x;
    input.pen_y=y;
}
}
