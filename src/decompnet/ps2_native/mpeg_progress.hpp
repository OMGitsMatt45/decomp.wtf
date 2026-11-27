#pragma once

#include <cstdint>

namespace ps2_stubs {

// One-based ordinal of the last source picture delivered to guest memory by
// the most recently delivering decoder. Returns zero before its first picture
// and after that decoder is reset, removed, or moved to a new stream.
// Reading progress does not drive decode, advance playback, or count blank frames.
std::uint32_t moviePicturesDelivered();

}  // namespace ps2_stubs
