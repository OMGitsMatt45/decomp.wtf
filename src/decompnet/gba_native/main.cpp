// Independent desktop player and qualification harness. Cartridge code is emitted in game/.
#include "anygba/system.hpp"
#include "source_counts.h"
#include "anygba/sha256.h"
#include "save/save.h"
#include "cheats.hpp"
#include "cheat_catalog.hpp"
#include "customization.hpp"
#include <charconv>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <string_view>
#include <sstream>
#include <iomanip>
#include <map>
#ifdef GBA_WITH_DESKTOP
#include "video.hpp"
#include "frame_input.hpp"
#include "cheat_menu.hpp"
#endif

extern "C" const anygba_game anygba_game_info;
extern "C" const anygba_bios anygba_compiled_bios;

namespace {
std::string json_string(std::string_view value) {
    constexpr char hex[]="0123456789abcdef";
    std::string out="\"";
    for(unsigned char c:value){
        if(c=='"'||c=='\\'){out+='\\';out+=char(c);}
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=char(c);
    }
    return out+'"';
}
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
std::map<uint64_t,uint16_t> buttons(const std::filesystem::path& path){
    std::map<uint64_t,uint16_t> result;if(path.empty())return result;
    std::ifstream file(path);if(!file)throw anygba::Error("cannot open input script");
    std::string line;
    while(std::getline(file,line)){
        if(auto at=line.find('#');at!=line.npos)line.resize(at);
        std::istringstream stream(line);std::string f,k,extra;
        if(!(stream>>f))continue;
        if(!(stream>>k)||(stream>>extra))throw anygba::Error("input script needs frame and pressed mask");
        auto frame=number(f),mask=number(k);
        if(frame>1000000||mask>1023||result.size()>=100000||(!result.empty()&&frame<=result.rbegin()->first))
            throw anygba::Error("input script frames must increase and masks fit ten buttons");
        result[frame]=uint16_t(mask);
    }
    if(file.bad())throw anygba::Error("cannot read input script");
    return result;
}
}

int main(int argc, char** argv) {
    try {
        std::filesystem::path rom, save, capture, pcm, miss_log, input_script, menu_input_script, display_capture, bios;
        std::uint64_t frames = 8, keys = 0;
        std::uint64_t present_every=1,resize_frame=0;
        int resize_width=0,resize_height=0,width=0,height=0;
        bool window=false,unpaced=false,fullscreen=false;
        bool run_game=true;
        bool open_settings=false;
        std::vector<std::string> cheat_codes;
        std::vector<std::string> preset_picks;
        std::vector<std::filesystem::path> cheat_files;
        std::string renderer="auto";
#ifdef GBA_GAME_DEFAULT
        frames=0;window=true;renderer=GBA_DEFAULT_RENDERER;
#endif
        std::vector<std::uint32_t> observe;
        bool reference = false;
        anygba::Options options;
#ifdef GBA_NATIVE_ONLY
        options.strict_static=true;
#endif
        options.log_misses = false; // Output JSON carries the exact miss set, no implicit cwd writes.
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg = argv[i];
            if (arg == "--help") {
#ifdef GBA_NATIVE_ONLY
                std::cout << "gba_pc --rom game.gba (native execution; no interpreter fallback)\n";
#else
                std::cout << "gba_probe --rom game.gba [--frames 8] [--strict-static | --interpreter]\n";
#endif
                std::cout <<
                    "  [--frames N] [--headless]\n"
                    "  [--save game.sav] [--keys 0x001] [--observe 0x02000000]...\n"
                    "  [--capture screen.ppm] [--audio-pcm audio.pcm] [--rtc-start unix-seconds]\n"
                    "  [--bios owner-gba-bios.bin] (optional; a translated BIOS is selected automatically)\n"
                    "  [--miss-log NEW_FILE] (input-bound feedback for the next translation)\n"
                    "  [--window] [--renderer auto|opengl|software] [--fullscreen]\n"
                    "  [--resolution WIDTHxHEIGHT] [--display-capture output.ppm]\n"
                    "  [--input-script FILE] [--menu-input-script FILE] (lines: frame pressed-mask)\n"
                    "  [--unpaced] [--present-every N] [--resize FRAME:WIDTHxHEIGHT]\n";
                std::cout << "  [--cheat [FORMAT:]CODE] [--cheats FILE] [--preset ID] [--settings] (F1/Esc cheat browser, F12 cheat button)\n";
                return 0;
            }
            if (arg == "--strict-static") { options.strict_static = true; continue; }
            if (arg == "--interpreter") {
#ifdef GBA_NATIVE_ONLY
                throw anygba::Error("this player contains no interpreter; configure GBA_BUILD_REFERENCE=ON and use gba_probe for reference testing");
#else
                reference = true; continue;
#endif
            }
            if (arg == "--window") { window=true;continue; }
            if (arg == "--headless") { window=false;continue; }
            if (arg == "--unpaced") { unpaced=true;continue; }
            if (arg == "--fullscreen") { fullscreen=true;window=true;continue; }
            if (arg == "--settings") { open_settings=true;window=true;continue; }
            if (arg != "--rom" && arg != "--bios" && arg != "--save" && arg != "--capture" && arg != "--audio-pcm" && arg != "--miss-log" &&
                arg != "--frames" && arg != "--keys" && arg != "--observe" && arg != "--rtc-start" &&
                arg != "--renderer" && arg != "--resolution" && arg != "--present-every" && arg != "--resize" &&
                arg != "--input-script" && arg != "--menu-input-script" && arg != "--display-capture" && arg != "--cheat" && arg != "--cheats" && arg != "--preset")
                throw anygba::Error("unknown option: "+std::string(arg));
            if (++i == argc) throw anygba::Error("missing option value");
            if (arg == "--rom") rom = argv[i];
            else if (arg == "--bios") bios = argv[i];
            else if (arg == "--save") save = argv[i];
            else if (arg == "--capture") capture = argv[i];
            else if (arg == "--audio-pcm") pcm = argv[i];
            else if (arg == "--miss-log") miss_log = argv[i];
            else if (arg == "--input-script") input_script=argv[i];
            else if (arg == "--menu-input-script") menu_input_script=argv[i];
            else if (arg == "--display-capture") display_capture=argv[i];
            else if (arg == "--cheat") cheat_codes.emplace_back(argv[i]);
            else if (arg == "--preset") preset_picks.emplace_back(argv[i]);
            else if (arg == "--cheats") cheat_files.emplace_back(argv[i]);
            else if (arg == "--renderer") renderer=argv[i];
            else if (arg == "--resolution" || arg == "--resize") {
                std::string_view value=argv[i];
                if(arg=="--resize") {auto colon=value.find(':');if(colon==value.npos)throw anygba::Error("resize needs FRAME:WIDTHxHEIGHT");resize_frame=number(value.substr(0,colon));value.remove_prefix(colon+1);}
                auto split=value.find('x');if(split==value.npos)throw anygba::Error("resolution needs WIDTHxHEIGHT");
                const auto w=number(value.substr(0,split)),h=number(value.substr(split+1));
                if(w<1||h<1||w>16384||h>16384)throw anygba::Error("invalid drawable size");
                if(arg=="--resize"){resize_width=int(w);resize_height=int(h);}else{width=int(w);height=int(h);}
            }
            else {
                const auto value = number(argv[i]);
                if (arg == "--frames") frames = value;
                else if (arg == "--present-every") present_every=value;
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
        std::filesystem::path asset_root;
#ifdef GBA_GAME_DEFAULT
        if(rom.empty()) {
            std::vector<std::filesystem::path> roots{std::filesystem::current_path(),std::filesystem::absolute(argv[0]).parent_path()};
            for(auto root:roots){
                for(int i=0;i<4&&!root.empty();++i,root=root.parent_path()) {
                    if(std::filesystem::is_regular_file(root/"assets/game.gba")){rom=root/"assets/game.gba";asset_root=root;break;}
                    if(root==root.parent_path())break;
                }
                if(!rom.empty())break;
            }
        }
#endif
        if (rom.empty() || (frames == 0&&!window) || frames > 1000000 || keys > 0x3ff || present_every<1||present_every>1000000 ||
            (reference && options.strict_static))
            throw anygba::Error("provide a ROM, 1..1000000 frames, valid keys and one CPU mode");
        if(renderer!="auto"&&renderer!="opengl"&&renderer!="software")throw anygba::Error("invalid renderer");
        if(!window&&!display_capture.empty())throw anygba::Error("display capture requires --window");
        auto script=buttons(input_script),menu_script=buttons(menu_input_script);
        if(!menu_input_script.empty()&&(!window||menu_script.empty()))throw anygba::Error("menu input scripts require a desktop window and at least one input row");
        std::ifstream in(rom, std::ios::binary);
        if (!in || std::filesystem::file_size(rom) != anygba_game_info.rom_size)
            throw anygba::Error("cartridge size differs from generated code");
        std::vector<std::uint8_t> data{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
        if (anygba::sha256_hex(data) != anygba_game_info.rom_sha256)
            throw anygba::Error("cartridge SHA-256 differs from generated code");
        std::vector<uint8_t> bios_data;
        if (!bios.empty()) {
            std::ifstream file(bios,std::ios::binary);
            if (!file || std::filesystem::file_size(bios)!=16384) throw anygba::Error("GBA BIOS must contain exactly 16384 bytes");
            bios_data.assign(std::istreambuf_iterator<char>(file),std::istreambuf_iterator<char>());
            if(file.bad()||bios_data.size()!=16384)throw anygba::Error("GBA BIOS must contain exactly 16384 readable bytes");
        } else if(anygba_compiled_bios.image) {
            bios_data.assign(anygba_compiled_bios.image,anygba_compiled_bios.image+16384);
        }
        options.compiled_bios=&anygba_compiled_bios;
        options.relocated_entries=anygba_relocated_entries;
        options.relocated_count=anygba_relocated_count;
#ifdef GBA_GAME_DEFAULT
        if(save.empty())save=(asset_root.empty()?std::filesystem::current_path():asset_root)/"saves"/(std::string(anygba_game_info.rom_sha256).substr(0,16)+".sav");
#endif
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
        if(!bios_data.empty())system->set_bios_image(bios_data);
        uint16_t scripted=script.contains(0)?script.at(0):0;
        system->set_keys(static_cast<std::uint16_t>(keys)|scripted);
#ifdef GBA_WITH_DESKTOP
        std::unique_ptr<gba_video::Display> display;
        std::unique_ptr<gba_video::Scene> scene;
        if(window){scene=std::make_unique<gba_video::Scene>();gba_video::Options view;view.renderer=renderer;view.width=width;view.height=height;
            view.fullscreen=fullscreen;view.readback=!display_capture.empty();display=std::make_unique<gba_video::Display>(view);
            system->on_line_rendered=[&](anygba::System& s,unsigned line){scene->capture(s,line);};}
#else
        if(window)throw anygba::Error("this build is headless; configure with -DGBA_WITH_DESKTOP=ON");
#endif
        std::unique_ptr<anygba::save::SaveFile> persistence;
        if (!save.empty()) {
            persistence = std::make_unique<anygba::save::SaveFile>(save, system->backup());
            persistence->load();
        }
        gba_frontend::Cheats cheats;
        auto cheat_path=save;if(!cheat_path.empty())cheat_path+=".cheats.toml";
        cheats.load(cheat_path);
        for(const auto& file:cheat_files)cheats.load_once(file);
        for(const auto& code:cheat_codes)cheats.add_once(code);
        gba_customization::configure(*system);
        auto& catalog=gba_frontend::game_cheat_catalog();catalog.load(save);
        for(const auto& id:preset_picks)if(auto error=catalog.set_enabled(id,true,false))throw anygba::Error(*error);
#if defined(GBA_WITH_DESKTOP)
        gba_frontend::CheatBrowser browser;
        browser.set_input_script(menu_script);
        uint16_t menu_blocked=0,previous_menu_keys=0;
        if(open_settings){
            if(!display)throw anygba::Error("--settings requires a desktop window; remove --headless.");
            if(!browser.show(*display,catalog,cheats,gba_customization::description()))run_game=false;
            menu_blocked=browser.held_on_close();
        }
#else
        if(open_settings)throw anygba::Error("The cheat browser requires a desktop build. Cheat files and --preset work headlessly.");
#endif
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
            if(auto value=script.find(s.frames());value!=script.end())scripted=value->second;
            uint16_t live=0;
            bool cheat_button=false;
#ifdef GBA_WITH_DESKTOP
            if(display){
                const bool in_menu=catalog.available(s);
                auto input=gba_frontend::present_and_sample(*display,[&]{
                    if(resize_width&&s.frames()==resize_frame)display->resize(resize_width,resize_height);
                    display->audio(samples,unpaced);
                    if(s.frames()%present_every==0||(frames&&s.frames()>=frames)){
                        if(in_menu)browser.present_hint(*display,s.framebuffer());else display->present(*scene,s.framebuffer());
                    }
                },!unpaced);
                live=input.keys;cheat_button=input.cheat_button;
                menu_blocked&=live;live&=uint16_t(~menu_blocked);
                if(!input.running)s.stop();
                const auto menu_keys=uint16_t(live|scripted|keys);
                if(input.running&&(input.settings||(in_menu&&(menu_keys&~previous_menu_keys&256)))){
                    if(!browser.show(*display,catalog,cheats,gba_customization::description()))s.stop();
                    menu_blocked=browser.held_on_close();live=0;
                }
                previous_menu_keys=menu_keys;
            }
#endif
            s.set_keys(uint16_t(keys)|scripted|live);
            cheats.apply(s,uint16_t(keys)|scripted|live,cheat_button);
            catalog.apply(s,uint16_t(keys)|scripted|live,cheat_button);
            if (frames&&s.frames() >= frames) s.stop();
        };
        if(run_game)system->run();
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
        bool gpu=false,audio_device=false;std::string selected="headless",device;
        uint64_t menu_openings=0,menu_frames=0;
        int drawable_width=0,drawable_height=0;
#ifdef GBA_WITH_DESKTOP
        if(display){selected=display->renderer();device=display->device();gpu=selected=="opengl";audio_device=display->audio_device();menu_openings=browser.openings();menu_frames=browser.presented_frames();
            drawable_width=display->width();drawable_height=display->height();
            if(!display_capture.empty()){
                if(display->pixels().empty())throw anygba::Error("no display frame was captured");
                std::string header="P6\n"+std::to_string(drawable_width)+" "+std::to_string(drawable_height)+"\n255\n";
                header.append(reinterpret_cast<const char*>(display->pixels().data()),display->pixels().size());
                bytes(display_capture,header.data(),header.size());
            }
        }
#endif
        const auto image_hash = anygba::sha256_hex(std::span<const std::uint8_t>(
            reinterpret_cast<const std::uint8_t*>(rgb.data()), rgb.size()));
        std::cout << "{\"frames\":" << system->frames() << ",\"cycles\":" << system->now()
            << ",\"functions\":" << GBA_GENERATED_FUNCTIONS
            << ",\"native_entry_points\":" << anygba_game_info.function_count
            << ",\"reference_interpreter\":" << (reference ? "true" : "false")
            << ",\"interpreted_cycles\":" << system->interpreted_cycles()
            << ",\"enabled_cheats\":" << cheats.enabled()+catalog.enabled_count()
            << ",\"builtin_presets\":" << catalog.presets().size()
            << ",\"enabled_presets\":" << catalog.enabled_count()
            << ",\"menu_openings\":" << menu_openings << ",\"menu_frames\":" << menu_frames
            << ",\"game_customized\":" << (GBA_CUSTOMIZED?"true":"false")
            << ",\"customization\":" << json_string(gba_customization::description())
            << ",\"bios_sha256\":" << std::quoted(bios_data.empty()?std::string():anygba::sha256_hex(bios_data))
            << ",\"bios_native_dispatches\":" << system->bios_native_instructions()
            << ",\"rtc\":" << (system->has_rtc() ? "true" : "false")
            << ",\"audio_frames\":" << audio_frames << ",\"screen_sha256\":\"" << image_hash
            << "\",\"gpu_rendering\":"<<(gpu?"true":"false")<<",\"renderer\":"<<std::quoted(selected)
            <<",\"device\":"<<std::quoted(device)<<",\"audio_device\":"<<(audio_device?"true":"false")
            <<",\"drawable\":["<<drawable_width<<','<<drawable_height<<"],\"retail_qualified\":false,\"observed\":[";
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
#ifdef GBA_NATIVE_ONLY
        std::cerr << "gba_pc: " << error.what() << '\n';
#else
        std::cerr << "gba_probe: " << error.what() << '\n';
#endif
        return 1;
    }
}
