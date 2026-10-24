// SPDX-License-Identifier: MIT
// Immutable code guards for source-shipped PS2 modules. No interpreter fallback.
#pragma once
#include <cstdint>
#include <cstring>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>

namespace decomp_ps2 {
class CodeMismatch final : public std::runtime_error {
public:
    explicit CodeMismatch(std::string_view identity)
        : std::runtime_error("PS2 native code mismatch: " + std::string(identity)) {}
};

inline void check_code(const uint8_t *ram, uint32_t physical,
                       std::span<const uint8_t> expected, std::string_view identity) {
    if (!ram || expected.empty() || physical >= 0x02000000u ||
        expected.size() > 0x02000000u - physical)
        throw std::invalid_argument("PS2 module guard exceeds EE RAM");
    if (std::memcmp(ram + physical, expected.data(), expected.size()) != 0)
        throw CodeMismatch(identity);
}
} // namespace decomp_ps2
