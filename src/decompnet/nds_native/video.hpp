// SPDX-License-Identifier: MIT. Original decomp.wtf native presentation layer.
#pragma once
#include <dsr/gpu3d.h>
#include <dsr/machine.h>
#include <SDL.h>
#include <array>
#include <deque>
#include <memory>
#include <string>
#include <vector>

namespace video {
struct Texture {
    uint32_t param=0,palette=0;
    int width=0,height=0;
    std::vector<uint8_t> rgba;
};
// Own every byte: capture occurs at the 3D render boundary, before VRAM or
// geometry changes. Presentation latches that result before the next DS step.
struct Scene {
    std::vector<dsr::Gpu3DVertex> vertices;
    std::vector<dsr::Gpu3DPolygon> polygons;
    std::vector<uint16_t> order;
    std::vector<Texture> textures;
    std::array<uint8_t,256*192> safe{};
    std::array<uint32_t,32> toon{};
    std::array<uint32_t,8> edge{};
    std::array<uint8_t,32> fog_density{};
    uint32_t control=0,clear_color=0,clear_depth=0,alpha_ref=0,swap_mode=0;
    uint32_t fog_color=0,fog_offset=0;
    uint64_t generation=0,serial=0;
    bool widescreen=false;
    bool supported=true;
    static Scene capture(dsr::Machine& machine);
};
struct Frame {
    const Scene* scene=nullptr;
    const uint32_t* top=nullptr;
    const uint32_t* bottom=nullptr;
    const uint8_t* three_d=nullptr;
    bool on_top=false;
    const uint64_t* top_origins=nullptr;
    const uint64_t* bottom_origins=nullptr;
    const std::deque<Scene>* history=nullptr;
    const uint64_t* top_foreground=nullptr;
    const uint64_t* bottom_foreground=nullptr;
    const uint8_t* top_brightness=nullptr;
    const uint8_t* bottom_brightness=nullptr;
};
struct Options {
    std::string renderer="auto";
    int width=0,height=0; // Zero chooses an initial size from the active monitor.
    bool fullscreen=false,readback=false;
    bool dynamic_widescreen=false;
    bool expand_visibility=false;
};
class Display {
public:
    explicit Display(Options options);
    ~Display();
    Display(const Display&)=delete;
    Display& operator=(const Display&)=delete;
    void present(const Frame& frame);
    void key(const SDL_KeyboardEvent& event);
    bool touch(int window_x,int window_y,int& ds_x,int& ds_y) const;
    // Last presented output, top-to-bottom, including UI and letterboxing.
    std::vector<uint32_t> read_pixels() const;
    int width() const;
    int height() const;
    const std::string& renderer() const;
    const std::string& device() const;
    uint64_t polygons_drawn() const;
    // Native LCD texels actually replayed from captured 3D in the last frame.
    uint64_t captured_pixels() const;
    int render_scale() const;
    // 0 for the ordinary two-LCD layout; otherwise the live drawable aspect.
    float world_aspect() const;
    const std::string& layout() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
