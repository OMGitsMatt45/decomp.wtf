#include "hash.hpp"
#include "layout.h"

#ifdef IMAGE_SHA256
extern "C" int switch_asset_matches(const char* path) {
    try { return input_sha256(path) == IMAGE_SHA256; }
    catch (...) { return 0; }
}
#endif

extern "C" int switch_asset_matches_expected(const char* path, const char* expected) {
    try { return input_sha256(path) == expected; }
    catch (...) { return 0; }
}
