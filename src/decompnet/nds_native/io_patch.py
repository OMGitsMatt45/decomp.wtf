"""Explicit storage-register handling in the copied, pinned DS runtime."""
from pathlib import Path


def patch(root):
    path=Path(root)/'runtime/core/src/io.cpp'
    text=path.read_text(encoding='utf-8')
    changes={
        '        const std::uint32_t offset = addr & 0x1fffu;\n        if (wifi_register_mapped(offset)) {\n            const std::uint32_t base =':
        '''        const std::uint32_t ram_offset = addr & 0x7fffu;
        if (ram_offset >= 0x4000 && ram_offset + width / 8 <= 0x6000) {
            std::uint32_t result = 0;
            for (int byte = 0; byte < width / 8; ++byte)
                result |= std::uint32_t(wifi.ram[ram_offset - 0x4000 + byte]) << (8 * byte);
            return result;
        }
        const std::uint32_t offset = addr & 0x1fffu;
        if (wifi_register_mapped(offset)) {
            const std::uint32_t base =''',
        '        const std::uint32_t offset = addr & 0x1fffu;\n        if (wifi_register_mapped(offset)) {\n            const auto write_halfword =':
        '''        const std::uint32_t ram_offset = addr & 0x7fffu;
        if (ram_offset >= 0x4000 && ram_offset + width / 8 <= 0x6000) {
            for (int byte = 0; byte < width / 8; ++byte)
                wifi.ram[ram_offset - 0x4000 + byte] = std::uint8_t(value >> (8 * byte));
            return;
        }
        const std::uint32_t offset = addr & 0x1fffu;
        if (wifi_register_mapped(offset)) {
            const auto write_halfword =''',
        '    case 0x0130:\n        value = keyinput':
        '''    case 0x00e0: case 0x00e4: case 0x00e8: case 0x00ec:
        // ARM9 DMA fill latches are ordinary 32-bit storage, including
        // byte/halfword access and reads by a fixed-source DMA transfer.
        value = load_shadow(io_shadow[ci], base_off);
        if (id != CpuId::Arm9) log_unimplemented(id, base, width);
        break;
    case 0x0130:
        value = keyinput''',
        '    switch (off) {\n    case 0x0004:':
        '''    if (id == CpuId::Arm9 && off >= 0x00e0 && off < 0x00f0) {
        save_shadow(io_shadow[ci], off, value, width);
        return;
    }
    switch (off) {
    case 0x0134: case 0x0135:
        if (id == CpuId::Arm7) {
            // RCNT is a 16-bit GPIO control latch. A word write must not
            // modify the adjacent read-only extended key input register.
            const int bits = std::min(width, static_cast<int>(0x0136u - off) * 8);
            save_shadow(io_shadow[ci], off, value, bits);
            return;
        }
        break;
    case 0x0004:''',
    }
    for before,after in changes.items():
        if text.count(before)!=1:
            raise ValueError('pinned DS storage-register integration site differs')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
    path=Path(root)/'runtime/core/src/core_internal.h'
    text=path.read_text(encoding='utf-8')
    before='struct WifiState {\n'
    if text.count(before)!=1:raise ValueError('pinned DS wireless RAM state differs')
    text=text.replace(before,before+'    std::array<std::uint8_t, 0x2000> ram{};\n')
    before='    void reset() {\n        baseband.fill(0);'
    if text.count(before)!=1:raise ValueError('pinned DS wireless RAM reset differs')
    text=text.replace(before,'    void reset() {\n        ram.fill(0);\n        baseband.fill(0);')
    path.write_text(text,encoding='utf-8')
