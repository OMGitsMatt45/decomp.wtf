#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>
namespace anygba { class System; }
namespace gba_video {
struct Scene {
    static constexpr int row_words=902, metadata_words=row_words*160;
    std::array<uint32_t,metadata_words> rows{};
    std::vector<uint32_t> vram;
    uint64_t generation=~uint64_t{0};
    uint32_t vram_offset=0;
    void capture(anygba::System& system,unsigned line);
};
struct Options {
    std::string renderer="auto";
    int width=0,height=0;
    bool fullscreen=false,readback=false,hidden=false;
};
class Display {
public:
    explicit Display(Options options);
    ~Display();
    bool poll(uint16_t& keys);
    void present(const Scene& scene,std::span<const uint16_t> software_frame);
    void audio(std::span<const int16_t> samples,bool unpaced=false);
    void resize(int width,int height);
    void pace();
    std::string renderer() const;
    std::string device() const;
    bool audio_device() const;
    int width() const;
    int height() const;
    const std::vector<uint8_t>& pixels() const;
private:
    struct Impl;
    std::unique_ptr<Impl> p;
};
}
