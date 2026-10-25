// CC0 original GIF packets: geometry, image upload, readback and GS mode change.
#include "gs_interface.hpp"
#include "device.hpp"
#include "context.hpp"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

using namespace ParallelGS;
using namespace Vulkan;

static void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

static void quote(const char *text) {
    std::putchar('"');
    for (auto p = reinterpret_cast<const unsigned char *>(text); *p; ++p) {
        if (*p == '"' || *p == '\\') { std::putchar('\\'); std::putchar(*p); }
        else if (*p < 32) std::printf("\\u%04x", *p);
        else std::putchar(*p);
    }
    std::putchar('"');
}

static unsigned draw(GSInterface &gs, unsigned width, unsigned image_flag) {
    gs.reset_context_state();
    std::memset(gs.map_vram_write(0, 4 * 1024 * 1024), 0, 4 * 1024 * 1024);
    gs.end_vram_write(0, 4 * 1024 * 1024);
    PRMODECONTBits mode = {}; mode.AC = 1; gs.write_register(RegisterAddr::PRMODECONT, mode);
    FRAMEBits frame = {}; frame.FBW = width / 64; frame.PSM = PSMCT32;
    gs.write_register(RegisterAddr::FRAME_1, frame);
    ZBUFBits z = {}; z.ZMSK = 1; gs.write_register(RegisterAddr::ZBUF_1, z);
    TESTBits test = {}; gs.write_register(RegisterAddr::TEST_1, test);
    SCISSORBits scissor = {}; scissor.SCAX1 = width - 1; scissor.SCAY1 = width - 1;
    gs.write_register(RegisterAddr::SCISSOR_1, scissor);

    // PACKED GIF tag, three loops, RGBAQ/XYZ2, PRE=1, triangle list.
    std::vector<uint64_t> packet(2 + 3 * 4);
    packet[0] = 3ull | (1ull << 15) | (1ull << 46) | (3ull << 47) | (2ull << 60);
    packet[1] = 0x51;
    unsigned x[] = {width / 8, width * 7 / 8, width / 8};
    unsigned y[] = {width / 8, width / 8, width * 7 / 8};
    for (unsigned n = 0; n < 3; ++n) {
        packet[2 + n * 4] = 255; packet[3 + n * 4] = 128ull << 32;
        packet[4 + n * 4] = uint64_t(x[n] * 16) | (uint64_t(y[n] * 16) << 32);
        packet[5 + n * 4] = 0;
    }
    gs.gif_transfer(3, packet.data(), packet.size() * sizeof(uint64_t));

    // Host-to-local image transfer into a separate 2x2 rectangle. Exercise
    // FLG=2 and FLG=3; both describe original image data, not draw instructions.
    BITBLTBUFBits transfer = {}; transfer.DBW = width / 64; transfer.DPSM = PSMCT32;
    gs.write_register(RegisterAddr::BITBLTBUF, transfer);
    TRXPOSBits position = {}; position.DSAX = width - 4; position.DSAY = width - 4;
    gs.write_register(RegisterAddr::TRXPOS, position);
    TRXREGBits area = {}; area.RRW = 2; area.RRH = 2; gs.write_register(RegisterAddr::TRXREG, area);
    TRXDIRBits direction = {}; gs.write_register(RegisterAddr::TRXDIR, direction);
    uint64_t image[] = {1ull | (1ull << 15) | (uint64_t(image_flag) << 58), 0,
                       0x8000ff008000ff00ull, 0x8000ff008000ff00ull};
    gs.gif_transfer(3, image, sizeof(image));
    gs.flush();

    transfer = {}; transfer.SBW = width / 64; transfer.SPSM = PSMCT32;
    gs.write_register(RegisterAddr::BITBLTBUF, transfer);
    position = {}; gs.write_register(RegisterAddr::TRXPOS, position);
    area.RRW = width; area.RRH = width; gs.write_register(RegisterAddr::TRXREG, area);
    direction.XDIR = 1; gs.write_register(RegisterAddr::TRXDIR, direction);
    std::vector<uint32_t> pixels(width * width);
    gs.read_transfer_fifo(pixels.data(), static_cast<uint32_t>(pixels.size() / 4));
    unsigned red = 0, green = 0;
    for (auto pixel : pixels) { red += pixel == 0x800000ff; green += pixel == 0x8000ff00; }
    unsigned side = width * 3 / 4;
    require(red == side * (side + 1) / 2, "original triangle coverage differs");
    require(green == 4, "original image transfer differs");
    require(pixels[(width / 4) * width + width / 4] == 0x800000ff, "triangle interior differs");
    require(pixels[(width - 1) * width + width - 1] == 0, "background differs");
    return red;
}

int main() {
    try {
        require(Context::init_loader(nullptr), "Vulkan loader unavailable");
        Context context; context.set_num_thread_indices(1);
        // Use the descriptor-set path. Optional descriptor-buffer/heap paths
        // are outside this assessment and are not required by the GS API.
        require(context.init_instance_and_device(nullptr, 0, nullptr, 0, 0), "Vulkan device initialization failed");
        Device device; device.set_context(context); device.init_frame_contexts(2);
        GSInterface gs; GSOptions options = {};
        require(gs.init(&device, options), "GS Vulkan initialization failed");
        unsigned first = draw(gs, 64, 2), second = draw(gs, 128, 3);
        device.wait_idle();
        auto &properties = device.get_gpu_properties();
        std::printf("{\"api\":\"vulkan\",\"device\":"); quote(properties.deviceName);
        std::printf(",\"software_device\":%s,\"red_pixels\":[%u,%u],\"image_pixels\":[4,4],"
                    "\"gs_dimensions\":[64,128],\"gif_image_flags\":[2,3],\"passed\":true}\n",
            properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU ? "true" : "false", first, second);
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "PS2 GS probe failed: %s\n", error.what());
        return 1;
    }
}
