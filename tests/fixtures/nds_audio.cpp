// SPDX-License-Identifier: CC0-1.0. Original queue qualification, no GPU or ROM data.
#include "audio_queue.hpp"
#include <iostream>
#include <vector>

void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
void audio_queue_checks() {
    SDL_AudioSpec spec{};spec.freq=48000;spec.channels=2;spec.format=AUDIO_S16SYS;
    spec.samples=ds_host::audio_device_samples;
    const auto device=SDL_OpenAudioDevice(nullptr,0,&spec,nullptr,0);
    require(device!=0,"paused dummy audio device");
    std::vector<uint8_t> block(480*4,0x34),backlog(28800*4,0x12);
    ds_host::AudioQueueStats stats;
    for(unsigned i=0;i<5;++i)require(ds_host::queue_game_audio(device,block,48000,&stats),"ten-ms blocks admitted through 50ms");
    require(SDL_GetQueuedAudioSize(device)==5*block.size(),"accepted PCM reaches the real SDL queue");
    require(!ds_host::queue_game_audio(device,block,48000,&stats),"queue cannot grow beyond 50ms");
    require(SDL_GetQueuedAudioSize(device)==5*block.size(),"overflow preserves queued sound");
    require(stats.maximum_queued_bytes==5*block.size()&&stats.declined_blocks==1,"queue latency telemetry");
    SDL_ClearQueuedAudio(device);
    require(SDL_QueueAudio(device,backlog.data(),Uint32(backlog.size()))==0,"prepare external pre-existing backlog");
    require(!ds_host::queue_game_audio(device,block,48000),"an existing backlog admits no more audio");
    require(SDL_GetQueuedAudioSize(device)==backlog.size(),"ordinary admission never flushes playing audio");
    require(ds_host::queue_game_audio(device,{},48000),"empty PCM remains a no-op even behind a backlog");
    SDL_ClearQueuedAudio(device);
    bool rejected=false;
    try{ds_host::queue_game_audio(device,std::span<const uint8_t>(block).first(3),48000);}
    catch(const std::runtime_error&){rejected=true;}
    require(rejected,"partial stereo PCM is rejected");
    SDL_CloseAudioDevice(device);
    std::cout<<"SDL audio backlog preservation checks passed\n";
}
int main() {
    SDL_SetMainReady();
    try {require(SDL_Init(SDL_INIT_AUDIO)==0,SDL_GetError());audio_queue_checks();}
    catch(const std::exception& error){std::cerr<<error.what()<<'\n';SDL_Quit();return 1;}
    SDL_Quit();return 0;
}
