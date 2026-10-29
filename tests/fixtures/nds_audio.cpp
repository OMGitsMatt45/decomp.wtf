// SPDX-License-Identifier: CC0-1.0. Original queue qualification, no GPU or ROM data.
#include "audio_queue.hpp"
#include <iostream>
#include <vector>

void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
void audio_queue_checks() {
    SDL_AudioSpec spec{};spec.freq=48000;spec.channels=2;spec.format=AUDIO_S16SYS;spec.samples=1024;
    const auto device=SDL_OpenAudioDevice(nullptr,0,&spec,nullptr,0);
    require(device!=0,"paused dummy audio device");
    // Newly opened queue-mode devices are paused, so counts are deterministic.
    std::vector<uint8_t> block(4800*4,0x34),backlog(28800*4,0x12);
    for(unsigned i=0;i<3;++i)require(ds_host::queue_game_audio(device,block,48000),"audio admitted through the exact 300ms boundary");
    require(SDL_GetQueuedAudioSize(device)==3*block.size(),"accepted PCM reaches the real SDL queue");
    require(!ds_host::queue_game_audio(device,block,48000),"overflow block is declined");
    require(SDL_GetQueuedAudioSize(device)==3*block.size(),"overflow preserves already queued sound");
    SDL_ClearQueuedAudio(device);
    require(SDL_QueueAudio(device,backlog.data(),Uint32(backlog.size()))==0,"prepare a pre-existing 600ms backlog");
    require(!ds_host::queue_game_audio(device,block,48000),"an existing backlog admits no additional audio");
    require(SDL_GetQueuedAudioSize(device)==backlog.size(),"clock drift never flushes the old backlog");
    SDL_ClearQueuedAudio(device);
    require(ds_host::queue_game_audio(device,{},48000)&&SDL_GetQueuedAudioSize(device)==0,"empty PCM is a no-op");
    bool rejected=false;
    try{ds_host::queue_game_audio(device,std::span<const uint8_t>(block).first(3),48000);}
    catch(const std::runtime_error&){rejected=true;}
    require(rejected,"partial stereo PCM is rejected");
    SDL_CloseAudioDevice(device);
    std::cout<<"SDL audio backlog preservation checks passed\n";
}

int main() {
    SDL_SetMainReady();
    try {
        require(SDL_Init(SDL_INIT_AUDIO)==0,SDL_GetError());
        audio_queue_checks();
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';SDL_Quit();return 1;}
    SDL_Quit();return 0;
}
