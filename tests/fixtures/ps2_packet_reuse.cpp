// SPDX-License-Identifier: CC0-1.0
#include "runtime/gs/gs_threaded_backend.h"
#include "runtime/gs/ps2_gif_arbiter.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <new>
#include <stdexcept>

std::atomic<bool> tracking{false};
std::atomic<size_t> calls{0},bytes{0};
void *operator new(size_t size) {
    if(tracking.load(std::memory_order_relaxed)) {
        calls.fetch_add(1,std::memory_order_relaxed);bytes.fetch_add(size,std::memory_order_relaxed);
    }
    if(auto *memory=std::malloc(size?size:1))return memory;
    throw std::bad_alloc();
}
void operator delete(void *memory) noexcept {std::free(memory);}
void operator delete(void *memory,size_t) noexcept {std::free(memory);}
struct AllocationSample {
    AllocationSample(){calls=0;bytes=0;tracking=true;}
    ~AllocationSample(){tracking=false;}
};
struct State {
    std::mutex mutex;std::condition_variable event;bool entered=false,released=false;
    uint32_t commands=0;
    void release(){std::lock_guard lock(mutex);released=true;event.notify_all();}
};
struct Sink final:GSRasterBackend {
    State &state;explicit Sink(State &record):state(record){}
    void Initialize(uint8_t*,uint32_t) override{}
    void Reset() override{}
    void Submit(const GSPrimitiveBatch &batch) override {
        if(batch.vertices[0].z!=state.commands++)throw std::runtime_error("GS order or bytes changed");
        if(state.commands==1){std::unique_lock lock(state.mutex);state.entered=true;state.event.notify_all();state.event.wait(lock,[&]{return state.released;});}
    }
    void BeginTransfer(const GSTransferCommand&) override{}
    void UploadImage(const uint8_t*,uint32_t) override{}
    void Flush() override{}
    void TextureFlush() override{}
    void Sync(GSSyncReason) override{}
    PresentationFrame Present(const GSPresentationRequest&) override{return {};}
    bool ClearFramebuffer(const GSContext&,uint32_t) override{return true;}
    uint32_t ConsumeLocalToHostBytes(uint8_t*,uint32_t) override{return 0;}
    uint32_t ReadVram(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t) const override{return 0;}
    void WriteVram(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t) override{}
    void SnapshotVram(std::vector<uint8_t>&) const override{}
    GSTransferSnapshot GetTransferSnapshot() const override{return {};}
};

int main() try {
    uint8_t payload[96]{},seen[4]{};uint32_t packets=0;bool verifyOrder=true;
    GifArbiter gif([&](const uint8_t *data,uint32_t size){
        if(size!=sizeof(payload)||data[95]!=0x2bu)throw std::runtime_error("GIF bytes changed");
        if(verifyOrder){if(packets>=sizeof(seen))throw std::runtime_error("Unexpected GIF packet");seen[packets]=data[0];}
        ++packets;
    });
    const auto submit=[&](GifPathId path,uint8_t marker,bool hl=false,bool image=false){
        payload[0]=marker;payload[7]=image?8u:0u;payload[95]=0x2bu;
        gif.submit(path,payload,sizeof(payload),hl);payload[0]=0xffu;payload[95]=0xffu;
    };
    submit(GifPathId::Path2,2,true);submit(GifPathId::Path3,3,false,true);submit(GifPathId::Path1,1);
    gif.drain();
    if(packets!=3||seen[0]!=1||seen[1]!=3||seen[2]!=2||!gif.empty())throw std::runtime_error("GIF priority or ownership changed");
    verifyOrder=false;
    {AllocationSample sample;for(uint32_t i=0;i<5000u;++i){submit(GifPathId::Path1,4);gif.drain();}}
    const size_t gifAllocations=calls.load();
    if(packets!=5003||!gif.empty())throw std::runtime_error("GIF packets lost");

    State state;GSThreadedBackend worker(std::make_unique<Sink>(state),16u*1024u*1024u);
    struct Release{State &state;~Release(){state.release();}} release{state};
    worker.Initialize(nullptr,0);GSPrimitiveBatch batch{};worker.Submit(batch);
    {std::unique_lock lock(state.mutex);if(!state.event.wait_for(lock,std::chrono::seconds(5),[&]{return state.entered;}))throw std::runtime_error("GS gate timed out");}
    {AllocationSample sample;for(uint32_t i=1;i<=5000u;++i){batch.vertices[0].z=i;worker.Submit(batch);}}
    const size_t gsBytes=bytes.load();
    state.release();worker.Sync(GSSyncReason::Finish);
    if(state.commands!=5001u)throw std::runtime_error("GS commands lost");
    std::printf("{\"gif_allocations\":%zu,\"gs_allocated_bytes\":%zu,\"gif_packets\":%u,\"gs_commands\":%u}\n",gifAllocations,gsBytes,packets,state.commands);
    return 0;
}catch(const std::exception &error){std::fprintf(stderr,"%s\n",error.what());return 1;}
