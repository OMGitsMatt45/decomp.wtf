#include "hash.hpp"
#include "layout.h"

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <vector>

// Use the system's streaming SHA-256 provider for multi-gigabyte RomFS images.
// Keep checking every byte; a provider or read failure rejects the asset.
static std::string switch_input_sha256(const char* path) {
    struct Handles {
        BCRYPT_ALG_HANDLE algorithm = nullptr;
        BCRYPT_HASH_HANDLE hash = nullptr;
        ~Handles() {
            if (hash) BCryptDestroyHash(hash);
            if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
        }
    } handles;
    if (BCryptOpenAlgorithmProvider(&handles.algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
        BCryptCreateHash(handles.algorithm, &handles.hash, nullptr, 0, nullptr, 0, 0) < 0)
        throw std::runtime_error("could not initialize asset SHA-256");
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("could not open Switch asset");
    std::vector<unsigned char> buffer(1024 * 1024);
    while (input) {
        input.read(reinterpret_cast<char*>(buffer.data()), buffer.size());
        const auto count = input.gcount();
        if (count && BCryptHashData(handles.hash, buffer.data(), static_cast<ULONG>(count), 0) < 0)
            throw std::runtime_error("could not hash Switch asset");
    }
    if (!input.eof() || input.bad()) throw std::runtime_error("could not read Switch asset");
    unsigned char digest[32];
    if (BCryptFinishHash(handles.hash, digest, sizeof(digest), 0) < 0)
        throw std::runtime_error("could not finish asset SHA-256");
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    for (auto byte : digest) {
        result += hex[byte >> 4];
        result += hex[byte & 15];
    }
    return result;
}
#else
static std::string switch_input_sha256(const char* path) { return input_sha256(path); }
#endif

#ifdef IMAGE_SHA256
extern "C" int switch_asset_matches(const char* path) {
    try { return switch_input_sha256(path) == IMAGE_SHA256; }
    catch (...) { return 0; }
}
#endif

extern "C" int switch_asset_matches_expected(const char* path, const char* expected) {
    try { return switch_input_sha256(path) == expected; }
    catch (...) { return 0; }
}
