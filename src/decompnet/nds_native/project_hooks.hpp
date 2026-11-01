// SPDX-License-Identifier: MIT
#pragma once
#include <dsr/session.h>
#include <ostream>

// Game projects own this optional header; regeneration does not replace it.
#ifdef NDS_PROJECT_FEATURES
#include "project_features.hpp"
#else
namespace ds_project {
struct Features {
    void start(dsr::Session&,const dsr::MachineConfig&) {}
    bool input(dsr::Session&,dsr::InputState&) {return true;}
    void frame(dsr::Session&,const dsr::InputState&) {}
    void report(std::ostream&) const {}
};
}
#endif
