// SPDX-License-Identifier: MIT. Generated DS host audio queue policy.
#pragma once
#include <SDL.h>
#include <cstdint>
#include <span>
#include <stdexcept>

namespace ds_host {
// Bound clock drift by declining a new block, preserving sound already queued.
inline bool queue_game_audio(SDL_AudioDeviceID device,std::span<const std::uint8_t> pcm,unsigned rate) {
    constexpr unsigned frame_bytes=2*sizeof(std::int16_t);
    if(pcm.size()%frame_bytes)throw std::runtime_error("Incomplete stereo audio frame");
    const std::uint64_t budget=std::uint64_t(rate)*frame_bytes*3/10;
    if(SDL_GetQueuedAudioSize(device)+pcm.size()>budget)return false;
    if(!pcm.empty()&&SDL_QueueAudio(device,pcm.data(),Uint32(pcm.size()))!=0)
        throw std::runtime_error(SDL_GetError());
    return true;
}
}
