// N64 ROM analysis. MIT license; see the repository LICENSE.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif

namespace n64 {
using Bytes = std::vector<std::uint8_t>;
using Segment = std::array<std::int64_t, 3>;
using Range = std::array<std::int64_t, 2>;
static_assert(sizeof(Segment) == 3 * sizeof(std::int64_t));
static_assert(sizeof(Range) == 2 * sizeof(std::int64_t));
using Decoder = int (*)(std::uint32_t);
// Generic raw-deflate decoding is supplied by the host's zlib, not by ROM policy.
using Inflate = const std::uint8_t* (*)(const std::uint8_t*, std::size_t, std::size_t*, std::size_t*);
constexpr std::uint32_t return_instruction = 0x03e00008;
constexpr std::int64_t block_size = 0x400;
thread_local std::string error;

struct View {
    const std::uint8_t* data;
    std::size_t size;
    std::uint32_t word(std::size_t offset) const {
        if (offset > size || size - offset < 4) throw std::out_of_range("truncated N64 word");
        return (std::uint32_t(data[offset]) << 24) | (std::uint32_t(data[offset + 1]) << 16)
             | (std::uint32_t(data[offset + 2]) << 8) | data[offset + 3];
    }
};

struct Result {
    Bytes bytes;
    int format = 0;
    std::array<std::uint32_t, 5> header{};
    std::vector<Segment> segments;
    std::vector<std::pair<std::size_t, Bytes>> blocks;
};

template<class F> Result* run(F function) noexcept {
    error.clear();
    try {
        auto result = std::make_unique<Result>();
        function(*result);
        return result.release();
    } catch (const std::exception& e) { error = e.what(); }
    catch (...) { error = "native N64 analysis failed"; }
    return nullptr;
}

void normalize(View rom, Result& out) {
    if (rom.size < 4) throw std::invalid_argument("this doesn't look like an N64 ROM image (.z64, .n64 or .v64)");
    auto magic = rom.word(0);
    if (magic != 0x80371240 && magic != 0x37804012 && magic != 0x40123780)
        throw std::invalid_argument("this doesn't look like an N64 ROM image (.z64, .n64 or .v64)");
    if (rom.size % 4) throw std::invalid_argument("ROM size is not a multiple of 4 bytes; the file may be truncated");
    out.format = magic == 0x80371240 ? 0 : magic == 0x37804012 ? 1 : 2;
    out.bytes.assign(rom.data, rom.data + rom.size);
    if (out.format == 1) for (std::size_t i = 0; i < rom.size; i += 2) std::swap(out.bytes[i], out.bytes[i + 1]);
    if (out.format == 2) for (std::size_t i = 0; i < rom.size; i += 4) std::reverse(out.bytes.begin() + i, out.bytes.begin() + i + 4);
}

bool frame(std::uint32_t word) { return (word & 0xffff8000) == 0x27bd8000; }

std::vector<std::int64_t> calls(View rom, std::int64_t lo, std::int64_t hi, std::int64_t region) {
    std::vector<std::int64_t> out;
    for (auto at = lo; at + 4 <= hi; at += 4) {
        auto word = rom.word(at);
        if (word >> 26 == 3) out.push_back(((word & 0x03ffffff) << 2) | (region & 0xf0000000));
    }
    return out;
}

bool overlaps(const std::vector<Range>& ranges, std::int64_t lo, std::int64_t hi) {
    return std::any_of(ranges.begin(), ranges.end(), [&](const Range& range) { return range[0] < hi && lo < range[1]; });
}

struct Candidate { std::int64_t start, end, address; std::size_t hits; };

bool place(View rom, std::int64_t lo, std::int64_t hi, std::int64_t floor,
           const std::vector<std::int64_t>& external, const std::vector<Range>& known, Candidate& candidate,
           const std::vector<Range>& regions = {{0x80000000, 0x81000000}, {0x70000000, 0x80000000}}) {
    std::vector<std::int64_t> frames, returns;
    for (auto at = lo; at + 4 <= hi; at += 4) {
        auto word = rom.word(at);
        if (frame(word)) frames.push_back(at - lo);
        if (word == return_instruction) returns.push_back(at - lo);
    }
    if (frames.size() < 8 || returns.size() < 8) return false;
    std::size_t hits = 0;
    std::int64_t base = 0;
    std::set<std::int64_t> own;
    for (auto region : regions) {
        auto targets = calls(rom, lo, hi, region[0]);
        std::set<std::int64_t> unique(targets.begin(), targets.end());
        std::map<std::int64_t, std::size_t> votes;
        for (auto target : unique) for (auto offset : frames) {
            auto address = target - offset;
            if (region[0] <= address && address < region[1] && address % 4 == 0) ++votes[address];
        }
        for (auto vote : votes) if (vote.second > hits) {
            hits = vote.second; base = vote.first; own = unique;
        }
    }
    if (hits < std::max<std::size_t>(8, frames.size() / 10)) return false;
    auto first = frames.front();
    auto back = std::max(floor, lo - 2 * block_size) - lo;
    own.insert(external.begin(), external.end());
    for (auto target : own) if (back <= target - base && target - base < hi - lo
                              && !overlaps(known, target, target + 1)) first = std::min(first, target - base);
    candidate = {lo + first, std::min<std::int64_t>((lo + returns.back() + 8 + 15) & ~15, rom.size), base + first, hits};
    return true;
}

void find_segments(View rom, const Segment* taken, std::size_t count, Result& result) {
    auto size = std::int64_t(rom.size & ~std::size_t(3));
    std::vector<Range> known, known_addresses;
    for (std::size_t i = 0; i < count; ++i) {
        auto s = taken[i];
        if (s[0] < 0 || s[1] < s[0] || s[1] > size || s[0] % 4 || s[1] % 4)
            throw std::invalid_argument("N64 segment ranges must be aligned and inside the ROM");
        known.push_back({s[0], s[1]});
        known_addresses.push_back({s[2], s[2] + s[1] - s[0]});
    }
    std::vector<std::int64_t> external;
    for (auto range : known) for (auto address : calls(rom, range[0], range[1], 0x80000000))
        if (!overlaps(known_addresses, address, address + 1)) external.push_back(address);
    std::sort(known.begin(), known.end());
    std::vector<Range> gaps;
    std::int64_t position = 0x1000;
    for (auto range : known) {
        if (range[0] > position) gaps.push_back({position, range[0]});
        position = std::max(position, range[1]);
    }
    if (position < size) gaps.push_back({position, size});
    std::vector<Candidate> candidates;
    std::vector<std::array<std::int64_t, 3>> stretches;
    for (auto gap : gaps) {
        std::vector<Range> regions;
        for (auto offset = gap[0]; offset < gap[1] - 0x20; offset += block_size) {
            auto end = std::min(offset + block_size, gap[1]) & ~std::int64_t(3);
            bool code = false;
            for (auto at = offset; at + 4 <= end; at += 4) {
                auto word = rom.word(at);
                if (word == return_instruction || frame(word)) { code = true; break; }
            }
            if (!code) continue;
            if (!regions.empty() && offset <= regions.back()[1] + 2 * block_size) regions.back()[1] = end;
            else regions.push_back({offset, end});
        }
        auto floor = gap[0];
        for (auto region : regions) {
            stretches.push_back({region[0], region[1], floor});
            Candidate candidate;
            if (place(rom, region[0], region[1], floor, external, known_addresses, candidate)) {
                candidates.push_back(candidate); floor = candidate.end;
            }
        }
    }
    auto used = known_addresses;
    auto accept = [&](std::int64_t start, std::int64_t end, std::int64_t address) {
        if (overlaps(used, address, address + end - start)) return false;
        for (auto segment : result.segments) if (segment[0] < end && start < segment[1]) return false;
        result.segments.push_back({start, end, address}); used.push_back({address, address + end - start}); return true;
    };
    std::stable_sort(candidates.begin(), candidates.end(), [](auto a, auto b) { return a.hits > b.hits; });
    for (auto candidate : candidates) accept(candidate.start, candidate.end, candidate.address);
    std::vector<std::int64_t> mappings;
    for (auto segment : result.segments) {
        auto mapping = segment[2] - segment[0];
        if (std::find(mappings.begin(), mappings.end(), mapping) == mappings.end()) mappings.push_back(mapping);
    }
    std::unordered_set<std::int64_t> frame_addresses;
    for (std::int64_t at = 0; at + 4 <= size; at += 4) if (frame(rom.word(at))) frame_addresses.insert(at);
    for (auto stretch : stretches) {
        auto lo = stretch[0], hi = stretch[1];
        bool covered = false;
        for (auto s : result.segments) if ((s[0] <= lo && lo < s[1]) || (s[0] < hi && hi <= s[1])) covered = true;
        if (covered) continue;
        std::size_t best_hits = 0;
        std::int64_t best_mapping = 0;
        for (auto mapping : mappings) {
            std::size_t hits = 0;
            for (auto target : calls(rom, lo, hi, mapping + lo)) hits += frame_addresses.count(target - mapping);
            if (hits >= 3 && hits > best_hits) { best_hits = hits; best_mapping = mapping; }
        }
        if (!best_hits) continue;
        std::int64_t first = -1, last = -1;
        for (auto at = lo; at + 4 <= hi; at += 4) {
            if (first < 0 && frame(rom.word(at))) first = at;
            if (rom.word(at) == return_instruction) last = at;
        }
        if (first >= 0 && last >= 0) accept(first, std::min<std::int64_t>((last + 8 + 15) & ~15, rom.size), first + best_mapping);
    }
    std::sort(result.segments.begin(), result.segments.end());
}

Bytes yaz0(View input) {
    if (input.size < 16) throw std::out_of_range("truncated Yaz0 header");
    auto size = input.word(4);
    if (size > 64 * 1024 * 1024) throw std::invalid_argument("Yaz0 output exceeds 64 MiB");
    Bytes output; output.reserve(size);
    std::size_t at = 16;
    while (output.size() < size && at < input.size) {
        auto flags = input.data[at++];
        for (int bit = 7; bit >= 0; --bit) {
            if (output.size() >= size || at >= input.size) break;
            if ((flags >> bit) & 1) { output.push_back(input.data[at++]); continue; }
            if (input.size - at < 2) throw std::out_of_range("truncated Yaz0 reference");
            auto first = input.data[at++], second = input.data[at++];
            auto distance = std::size_t(((first & 15) << 8) | second) + 1;
            std::size_t length = first >> 4;
            if (!length) {
                if (at >= input.size) throw std::out_of_range("truncated Yaz0 length");
                length = input.data[at++] + 0x12;
            } else length += 2;
            if (distance > output.size()) throw std::out_of_range("invalid Yaz0 back-reference");
            for (std::size_t i = 0; i < length; ++i) output.push_back(output[output.size() - distance]);
        }
    }
    return output;
}

bool looks_like_code(View data) {
    std::size_t frames = 0, returns = 0;
    for (std::size_t at = 0; at + 4 <= data.size; at += 4) {
        auto word = data.word(at); frames += frame(word); returns += word == return_instruction;
    }
    return frames >= 16 && returns >= 16;
}

std::size_t next_marker(View rom, std::size_t start) {
    for (auto at = start; at + 1 < rom.size; ++at)
        if (rom.data[at] == 0x11 && (rom.data[at + 1] == 0x72 || rom.data[at + 1] == 0x73)) return at;
    return rom.size;
}

bool rare(View rom, std::size_t at, Inflate inflate, Bytes& output, std::size_t& consumed) {
    for (std::size_t skip : {5, 2}) {
        if (at + skip > rom.size) continue;
        std::size_t length = 0, used = 0;
        auto data = inflate(rom.data + at + skip, std::min<std::size_t>(rom.size - at - skip, 0x800000), &length, &used);
        if (!data || length < 0x1000 || length > 0x1000000) continue;
        if (skip == 5 && ((std::size_t(rom.data[at + 2]) << 16) | (std::size_t(rom.data[at + 3]) << 8) | rom.data[at + 4]) != length) continue;
        output.assign(data, data + length); consumed = skip + used; return true;
    }
    return false;
}

void unpack(View rom, Inflate inflate, Result& result) {
    auto at = next_marker(rom, 0);
    while (at < rom.size) {
        Bytes data;
        std::size_t consumed = 0;
        if (!rare(rom, at, inflate, data, consumed)) { at = next_marker(rom, at + 1); continue; }
        auto end = at + consumed;
        auto last_size = data.size();
        while (last_size == 0x1000) {
            auto next = next_marker(rom, end);
            Bytes page;
            if (next >= rom.size || next - end > 16 || !rare(rom, next, inflate, page, consumed)) break;
            last_size = page.size(); data.insert(data.end(), page.begin(), page.end()); end = next + consumed;
        }
        if (looks_like_code({data.data(), data.size()})) result.blocks.emplace_back(at, std::move(data));
        at = next_marker(rom, end);
    }
    for (std::size_t at = 0; at + 4 <= rom.size; ++at) {
        if (std::memcmp(rom.data + at, "Yaz0", 4) || rom.size - at < 16) continue;
        auto size = rom.word(at + 4);
        if (size < 0x1000 || size > 0x400000 || std::any_of(rom.data + at + 8, rom.data + at + 16, [](auto b) { return b != 0; })) continue;
        try {
            auto data = yaz0({rom.data + at, std::min<std::size_t>(rom.size - at, size * 2 + 0x100)});
            if (data.size() == size && looks_like_code({data.data(), data.size()})) result.blocks.emplace_back(at, std::move(data));
        } catch (const std::out_of_range&) {}
        at += 3;
    }
    std::stable_sort(result.blocks.begin(), result.blocks.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
}
} // namespace n64

API unsigned n64_abi() { return 1; }
API int n64_frame(std::uint32_t word) { return n64::frame(word); }
API const char* n64_error() { return n64::error.c_str(); }
API void n64_free(n64::Result* result) { delete result; }
API const std::uint8_t* n64_bytes(n64::Result* result) { return result->bytes.data(); }
API std::size_t n64_size(n64::Result* result) { return result->bytes.size(); }
API int n64_format(n64::Result* result) { return result->format; }
API const std::uint32_t* n64_header(n64::Result* result) { return result->header.data(); }
API std::size_t n64_segment_count(n64::Result* result) { return result->segments.size(); }
API const n64::Segment* n64_segments(n64::Result* result) { return result->segments.data(); }
API std::size_t n64_block_count(n64::Result* result) { return result->blocks.size(); }
API std::size_t n64_block_offset(n64::Result* result, std::size_t index) { return result->blocks.at(index).first; }
API std::size_t n64_block_size(n64::Result* result, std::size_t index) { return result->blocks.at(index).second.size(); }
API const std::uint8_t* n64_block_bytes(n64::Result* result, std::size_t index) { return result->blocks.at(index).second.data(); }

API n64::Result* n64_normalize(const std::uint8_t* data, std::size_t size) {
    return n64::run([&](auto& result) { n64::normalize({data, size}, result); });
}
API int n64_guess(const std::uint8_t* data, std::size_t size, n64::Decoder decoder) {
    std::size_t jumps = 0, branches = 0;
    n64::View rom{data, size};
    for (std::size_t at = 0; at + 4 <= size; at += 4) {
        auto word = rom.word(at);
        if (!decoder(word)) break;
        jumps += word >> 26 == 2;
        branches += word >> 16 == 0x1000;
    }
    return branches > jumps;
}
API n64::Result* n64_inspect(const std::uint8_t* data, std::size_t size, n64::Decoder decoder) {
    return n64::run([&](auto& result) {
        if (size < 0x40000) throw std::invalid_argument("file is too small to be an N64 ROM (" + std::to_string(size) + " bytes)");
        if (size > 64 * 1024 * 1024) throw std::invalid_argument("file is larger than any N64 cartridge (64 MiB)");
        n64::normalize({data, size}, result);
        n64::View rom{result.bytes.data(), result.bytes.size()};
        auto entry = rom.word(8);
        if (entry < 0x80000000 || entry >= 0x80800000) {
            std::ostringstream message;
            message << "the header's entry point 0x" << std::uppercase << std::hex << std::setfill('0') << std::setw(8) << entry << " is not in N64 RAM; is this a real ROM image?";
            throw std::invalid_argument(message.str());
        }
        result.header = {entry, rom.word(0x10), rom.word(0x14), rom.data[0x3f],
                         unsigned(n64_guess(rom.data + 0x1000, std::min<std::size_t>(size - 0x1000, 0x100000), decoder))};
    });
}
API n64::Result* n64_find_segments(const std::uint8_t* data, std::size_t size, const n64::Segment* taken, std::size_t count) {
    return n64::run([&](auto& result) { n64::find_segments({data, size}, taken, count, result); });
}
API n64::Result* n64_place(const std::uint8_t* data, std::size_t size, std::int64_t lo, std::int64_t hi,
                         std::int64_t floor, const std::int64_t* calls, std::size_t call_count,
                         const n64::Range* known, std::size_t known_count,
                         const n64::Range* regions, std::size_t region_count) {
    return n64::run([&](auto& result) {
        if (lo < 0 || hi < lo || std::uint64_t(hi) > size || (hi - lo) % 4)
            throw std::invalid_argument("invalid code placement range");
        n64::Candidate candidate;
        if (n64::place({data, size}, lo, hi, floor, {calls, calls + call_count}, {known, known + known_count},
                       candidate, {regions, regions + region_count})) {
            result.segments.push_back({candidate.start, candidate.end, candidate.address});
            result.header[0] = candidate.hits;
        }
    });
}
API n64::Result* n64_yaz0(const std::uint8_t* data, std::size_t size) {
    return n64::run([&](auto& result) { result.bytes = n64::yaz0({data, size}); });
}
API n64::Result* n64_unpack(const std::uint8_t* data, std::size_t size, n64::Inflate inflate) {
    return n64::run([&](auto& result) { n64::unpack({data, size}, inflate, result); });
}
