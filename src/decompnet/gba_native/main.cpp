// Headless qualification harness. Game logic is emitted in game/; no agent or app is needed.
#include "anygba/system.hpp"
#include "anygba/sha256.h"
#include "save/save.h"
#include <charconv>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <string_view>

extern "C" const anygba_game anygba_game_info;

namespace {
std::uint64_t number(std::string_view text) {
    int base = 10;
    if (text.starts_with("0x")) { text.remove_prefix(2); base = 16; }
    std::uint64_t value = 0;
    auto [end, error] = std::from_chars(text.data(), text.data()+text.size(), value, base);
    if (text.empty() || error != std::errc{} || end != text.data()+text.size())
        throw anygba::Error("invalid unsigned integer");
    return value;
}

void bytes(const std::filesystem::path& path, const char* data, std::size_t size) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out || !out.write(data, static_cast<std::streamsize>(size)))
        throw anygba::Error("cannot write capture: "+path.string());
}
}

int main(int argc, char** argv) {
    try {
        std::filesystem::path rom, save, capture, pcm, miss_log;
        std::uint64_t frames = 8, keys = 0;
        std::vector<std::uint32_t> observe;
        bool reference = false;
        anygba::Options options;
        options.log_misses = false; // Output JSON carries the exact miss set, no implicit cwd writes.
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg = argv[i];
            if (arg == "--help") {
                std::cout << "gba_probe --rom game.gba [--frames 8] [--strict-static | --interpreter]\n"
                    "  [--save game.sav] [--keys 0x001] [--observe 0x02000000]...\n"
                    "  [--capture screen.ppm] [--audio-pcm audio.pcm] [--rtc-start unix-seconds]\n"
                    "  [--miss-log NEW_FILE] (input-bound feedback for the next translation)\n";
                return 0;
            }
            if (arg == "--strict-static") { options.strict_static = true; continue; }
            if (arg == "--interpreter") { reference = true; continue; }
            if (arg != "--rom" && arg != "--save" && arg != "--capture" && arg != "--audio-pcm" && arg != "--miss-log" &&
                arg != "--frames" && arg != "--keys" && arg != "--observe" && arg != "--rtc-start")
                throw anygba::Error("unknown option: "+std::string(arg));
            if (++i == argc) throw anygba::Error("missing option value");
            if (arg == "--rom") rom = argv[i];
            else if (arg == "--save") save = argv[i];
            else if (arg == "--capture") capture = argv[i];
            else if (arg == "--audio-pcm") pcm = argv[i];
            else if (arg == "--miss-log") miss_log = argv[i];
            else {
                const auto value = number(argv[i]);
                if (arg == "--frames") frames = value;
                else if (arg == "--keys") keys = value;
                else if (arg == "--rtc-start") {
                    if (value > std::uint64_t{std::numeric_limits<std::int64_t>::max()})
                        throw anygba::Error("RTC epoch is out of range");
                    options.rtc_start = static_cast<std::int64_t>(value);
                } else {
                    if (value % 4 || !((value >= 0x02000000 && value <= 0x0203fffc) ||
                        (value >= 0x03000000 && value <= 0x03007ffc)) || observe.size() >= 1024)
                        throw anygba::Error("observations must be aligned EWRAM/IWRAM words (at most 1024)");
                    observe.push_back(static_cast<std::uint32_t>(value));
                }
            }
        }
        if (rom.empty() || frames == 0 || frames > 1000000 || keys > 0x3ff ||
            (reference && options.strict_static))
            throw anygba::Error("provide a ROM, 1..1000000 frames, valid keys and one CPU mode");
        std::ifstream in(rom, std::ios::binary);
        if (!in || std::filesystem::file_size(rom) != anygba_game_info.rom_size)
            throw anygba::Error("cartridge size differs from generated code");
        std::vector<std::uint8_t> data{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
        if (anygba::sha256_hex(data) != anygba_game_info.rom_sha256)
            throw anygba::Error("cartridge SHA-256 differs from generated code");
        if (!miss_log.empty()) {
            if (std::filesystem::exists(miss_log)) throw anygba::Error("choose a new miss-log file; existing work is preserved");
            std::ofstream header(miss_log, std::ios::binary);
            header << "# decomp.wtf.gba-misses/v1 sha256=" << anygba_game_info.rom_sha256 << '\n';
            header.close();
            if (!header) throw anygba::Error("cannot create coverage feedback file");
            options.log_misses = true;
            options.miss_log = miss_log;
        }
        // Validate all asset identities before opening saves or capture destinations.
        // CPU selection must preserve the cartridge hardware selected at generation.
        if (anygba_game_info.save_type) options.save_type = anygba_game_info.save_type;
        if (anygba_game_info.rtc >= 0) options.rtc = anygba_game_info.rtc ? "on" : "off";
        auto system = std::make_unique<anygba::System>(std::move(data), reference ? nullptr : &anygba_game_info, options);
        system->set_keys(static_cast<std::uint16_t>(keys));
        std::unique_ptr<anygba::save::SaveFile> persistence;
        if (!save.empty()) {
            persistence = std::make_unique<anygba::save::SaveFile>(save, system->backup());
            persistence->load();
        }
        std::ofstream audio;
        if (!pcm.empty()) {
            audio.open(pcm, std::ios::binary | std::ios::trunc);
            if (!audio) throw anygba::Error("cannot open PCM capture");
        }
        std::uint64_t audio_frames = 0;
        system->on_vblank = [&](anygba::System& s) {
            std::vector<std::int16_t> samples;
            s.drain_audio(samples);
            audio_frames += samples.size()/2;
            if (audio.is_open()) {
                // Explicit little endian; the file format is signed stereo PCM16 at 32768 Hz.
                for (std::uint16_t sample : samples) {
                    audio.put(static_cast<char>(sample)); audio.put(static_cast<char>(sample >> 8));
                }
                if (!audio) s.fail("PCM capture write failed");
            }
            if (persistence) if (auto error = persistence->on_frame()) s.fail(*error);
            if (s.frames() >= frames) s.stop();
        };
        system->run();
        if (persistence) if (auto error = persistence->flush()) throw anygba::Error(*error);
        if (audio.is_open()) { audio.close(); if (!audio) throw anygba::Error("PCM close failed"); }
        std::string rgb;
        for (std::uint16_t color : system->framebuffer()) {
            for (int shift : {0, 5, 10}) {
                const auto channel = (color >> shift) & 31;
                rgb += static_cast<char>((channel << 3) | (channel >> 2));
            }
        }
        if (!capture.empty()) {
            auto image = std::string("P6\n240 160\n255\n")+rgb;
            bytes(capture, image.data(), image.size());
        }
        const auto image_hash = anygba::sha256_hex(std::span<const std::uint8_t>(
            reinterpret_cast<const std::uint8_t*>(rgb.data()), rgb.size()));
        std::cout << "{\"frames\":" << system->frames() << ",\"cycles\":" << system->now()
            << ",\"functions\":" << anygba_game_info.function_count
            << ",\"reference_interpreter\":" << (reference ? "true" : "false")
            << ",\"interpreted_cycles\":" << system->interpreted_cycles()
            << ",\"rtc\":" << (system->has_rtc() ? "true" : "false")
            << ",\"audio_frames\":" << audio_frames << ",\"screen_sha256\":\"" << image_hash
            << "\",\"gpu_rendering\":false,\"retail_qualified\":false,\"observed\":[";
        for (std::size_t i = 0; i < observe.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << system->read32(observe[i]);
        }
        std::cout << "],\"misses\":[";
        std::size_t index = 0;
        for (auto address : system->misses()) { if (index++) std::cout << ','; std::cout << address; }
        std::cout << "]}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "gba_probe: " << error.what() << '\n';
        return 1;
    }
}
