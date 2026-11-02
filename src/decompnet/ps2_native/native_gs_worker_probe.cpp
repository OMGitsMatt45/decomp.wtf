// SPDX-License-Identifier: CC0-1.0
// Consumed preparations must release their frame while later work is blocked.
#include "runtime/gs/gs_threaded_backend.h"
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <stdexcept>
#include <string>

struct Gate {
    std::mutex mutex;std::condition_variable changed;bool entered=false,released=false;
    void block(){std::unique_lock lock(mutex);entered=true;changed.notify_all();changed.wait(lock,[&]{return released;});}
    void wait(){std::unique_lock lock(mutex);if(!changed.wait_for(lock,std::chrono::seconds(5),[&]{return entered;}))throw std::runtime_error("worker gate timed out");}
    void release(){std::lock_guard lock(mutex);released=true;changed.notify_all();}
};
struct Record {Gate first,last;std::weak_ptr<const GSPreparedPresentation> frame;};
struct Backend final:GSRasterBackend {
    Record &record;explicit Backend(Record &r):record(r){}
    void Initialize(uint8_t*,uint32_t) override{}
    void Reset() override{}
    void Submit(const GSPrimitiveBatch &batch) override {if(batch.vertices[0].z==1)record.first.block();else if(batch.vertices[0].z==2)record.last.block();}
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
    bool SupportsPreparedPresentation() const override{return true;}
    GSPresentationTicket PreparePresentation(const GSPresentationRequest&) override {
        auto frame=std::make_shared<GSPreparedPresentation>();record.frame=frame;return frame;
    }
};

int main(int argc,char **argv) try {
    if(argc!=2 || (std::string(argv[1])!="retained" && std::string(argv[1])!="released"))return 2;
    Record record;GSThreadedBackend worker(std::make_unique<Backend>(record));
    struct Release {Record &r;~Release(){r.first.release();r.last.release();}} release{record};
    worker.Initialize(nullptr,0);
    GSPrimitiveBatch first{},last{};first.vertices[0].z=1;last.vertices[0].z=2;
    worker.Submit(first);record.first.wait();
    auto frame=worker.PreparePresentation({});
    worker.Submit(last);worker.Flush();record.first.release();record.last.wait();
    frame.reset();const bool released=record.frame.expired();
    record.last.release();worker.Sync(GSSyncReason::Finish);
    std::printf("{\"frame_released_before_later_command_finishes\":%s}\n",released?"true":"false");
    return released==(std::string(argv[1])=="released")?0:1;
}catch(const std::exception &error){std::fprintf(stderr,"%s\n",error.what());return 1;}
