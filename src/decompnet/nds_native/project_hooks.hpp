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

namespace ds_project {
// Optional customization without requiring existing project Features to change.
template<class Feature,class Options>
void configure_video(Feature& feature,Options& options) {
    if constexpr(requires { feature.configure_video(options); }) feature.configure_video(options);
}
template<class Feature,class Frame>
void configure_frame(Feature& feature,dsr::Session& session,Frame& frame) {
    if constexpr(requires { feature.configure_frame(session,frame); })feature.configure_frame(session,frame);
}
}
