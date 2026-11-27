#include "runtime/gs/gs_threaded_backend.h"

#include <atomic>
#include <future>
#include <stdexcept>

using Aspect = GSPresentationAspect;

struct Picture final : GSPreparedPresentation {
    Aspect aspect = Aspect::Unknown;
};

struct TestBackend final : GSRasterBackend, GSPresentationAspectSource {
    std::atomic<Aspect> liveAspect = Aspect::Widescreen;
    std::promise<void> entered;
    std::future<void> resume;
    Aspect displayed = Aspect::Unknown;
    uint64_t tick = 0;

    explicit TestBackend(std::future<void> resume) : resume(std::move(resume)) {}
    void Initialize(uint8_t *, uint32_t) override {}
    void Reset() override {}
    void Submit(const GSPrimitiveBatch &) override {}
    void BeginTransfer(const GSTransferCommand &) override {}
    void UploadImage(const uint8_t *, uint32_t) override {}
    void Flush() override {}
    void TextureFlush() override {}
    void Sync(GSSyncReason) override {}
    PresentationFrame Present(const GSPresentationRequest &) override { return {}; }
    bool ClearFramebuffer(const GSContext &, uint32_t) override { return true; }
    uint32_t ConsumeLocalToHostBytes(uint8_t *, uint32_t) override { return 0; }
    uint32_t ReadVram(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t) const override { return 0; }
    void WriteVram(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t) override {}
    void SnapshotVram(std::vector<uint8_t> &) const override {}
    GSTransferSnapshot GetTransferSnapshot() const override { return {}; }
    bool SupportsPreparedPresentation() const override { return true; }
    Aspect capturePresentationAspect() const override { return liveAspect; }

    GSPresentationTicket PreparePresentation(const GSPresentationRequest &request) override {
        entered.set_value();
        resume.get();
        auto picture = std::make_shared<Picture>();
        picture->sourceVsyncTick = request.vsyncTick;
        picture->aspect = request.pictureAspect;
        return picture;
    }

    PresentationFrame DisplayPreparedPresentation(const GSPresentationTicket &ticket) override {
        const auto &picture = static_cast<const Picture &>(*ticket);
        displayed = picture.aspect;
        tick = picture.sourceVsyncTick;
        return {};
    }
};

int main() {
    std::promise<void> resume;
    auto backend = std::make_unique<TestBackend>(resume.get_future());
    auto *observed = backend.get();
    auto entered = observed->entered.get_future();
    GSThreadedBackend worker(std::move(backend));
    worker.Initialize(nullptr, 0);

    GSPresentationRequest request{};
    if (request.pictureAspect != Aspect::Unknown)
        return 1;
    request.vsyncTick = 41;
    request.pictureAspect = worker.capturePresentationAspect();
    const auto pending = worker.PreparePresentation(request);
    entered.get();
    observed->liveAspect = Aspect::Standard;
    request.pictureAspect = Aspect::Standard;
    request.vsyncTick = 42;
    resume.set_value();
    worker.DisplayPreparedPresentation(pending);
    return observed->displayed == Aspect::Widescreen && observed->tick == 41 ? 0 : 2;
}
