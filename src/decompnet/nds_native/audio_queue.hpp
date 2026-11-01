// SPDX-License-Identifier: MIT. Generated DS host audio queue policy.
#pragma once
#include <SDL.h>
#include <algorithm>
#include <cstdint>
#include <span>
#include <stdexcept>

namespace ds_host {
inline constexpr unsigned audio_queue_limit_ms=50;
inline constexpr unsigned audio_device_samples=512;
struct AudioQueueStats {
    uint64_t maximum_queued_bytes=0,declined_blocks=0;
};
// Keep a small bounded FIFO. Declining a block preserves the sound already
// playing; a pause explicitly clears the device and resampler at the caller.
inline bool queue_game_audio(SDL_AudioDeviceID device,std::span<const std::uint8_t> pcm,
                            unsigned rate,AudioQueueStats* stats=nullptr) {
    constexpr unsigned frame_bytes=2*sizeof(std::int16_t);
    if(!rate||pcm.size()%frame_bytes)throw std::runtime_error("Invalid stereo audio block");
    if(pcm.empty())return true;
    const uint64_t queued=SDL_GetQueuedAudioSize(device);
    if(stats)stats->maximum_queued_bytes=std::max(stats->maximum_queued_bytes,queued);
    const uint64_t budget=uint64_t(rate)*frame_bytes*audio_queue_limit_ms/1000;
    if(queued+pcm.size()>budget) {
        if(stats)++stats->declined_blocks;
        return false;
    }
    if(SDL_QueueAudio(device,pcm.data(),Uint32(pcm.size()))!=0)
        throw std::runtime_error(SDL_GetError());
    if(stats)stats->maximum_queued_bytes=std::max(stats->maximum_queued_bytes,queued+pcm.size());
    return true;
}
}
