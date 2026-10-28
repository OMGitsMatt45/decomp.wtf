// Optional presentation metadata; never changes emulated pixels or registers.
// Included inside Gpu2D::Impl by the pinned runtime integration.
struct CaptureOrigins {
    std::vector<std::uint64_t> vram = std::vector<std::uint64_t>(9U * kBankCapacity / 2U);
    std::array<std::uint64_t, kPixelsPerFrame> a{}, b{}, top{}, bottom{};
    std::array<std::uint64_t, kScreenWidth> composed{};
};
std::unique_ptr<CaptureOrigins> origins;
std::uint64_t origin_3d(unsigned x, unsigned y) const {
    if (!origins || !gpu3d) return 0;
    // Forty-eight generation bits outlast 149,000 years at 60 frames/second.
    return (gpu3d->render_serial() << 16U) | (y * 256U + x + 1U);
}
std::uint64_t mapped_origin(std::uint32_t address) const {
    if (!origins) return 0;
    address = vram_address(address);
    std::uint64_t result = 0;
    unsigned matches = 0;
    for (std::size_t i = 0; i < arm9_map_count; ++i) {
        const auto& m = arm9_maps[i];
        if (in_range(address, m.address, m.size)) {
            ++matches;
            result = origins->vram[bank_offset(m.bank, m.offset + address - m.address) / 2U];
        }
    }
    return matches == 1 ? result : 0; // OR-mapped banks have no unique origin.
}
std::uint64_t lcdc_origin(unsigned bank, unsigned offset) const {
    if (!origins || bank >= 4 || (vramcnt[bank] & 0x87U) != 0x80U) return 0;
    return origins->vram[bank_offset(bank, offset % kBankSizes[bank]) / 2U];
}
