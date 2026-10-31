"""Storage and offline wireless register corrections in the pinned DS runtime."""
from pathlib import Path
import re

# Documented MAC configuration/buffer latches (GBATEK DS Wi-Fi I/O map).
# Packet transfer and wireless timers remain separate services.
MAC_LATCH_MASKS = {
    0x004: 0x9fff, 0x006: 0x007f, 0x018: 0xffff, 0x01a: 0xffff, 0x01c: 0xffff,
    0x020: 0xffff, 0x022: 0xffff, 0x024: 0xffff, 0x02a: 0x07ff,
    0x050: 0xffff, 0x052: 0xffff, 0x056: 0x0fff, 0x058: 0x1ffe,
    0x05a: 0x0fff, 0x05c: 0x0fff, 0x062: 0x1ffe, 0x064: 0x0fff,
    0x068: 0x1ffe, 0x06c: 0x0fff, 0x074: 0x1ffe, 0x122: 0xffff,
    0x124: 0xffff, 0x128: 0xffff, 0x130: 0x0fff, 0x132: 0x8fff,
    0x134: 0xffff, 0x140: 0xffff, 0x142: 0xffff, 0x036: 0x0003,
}


def patch(root):
    path=Path(root)/'runtime/core/src/io.cpp'
    text=path.read_text(encoding='utf-8')
    permissions = re.search(r'(constexpr std::array<bool, 0x69> kBasebandWritable = \{)(.*?)(\n\};)', text, re.S)
    if not permissions:
        raise ValueError('pinned DS baseband permission table differs')
    values = re.findall(r'\b(?:true|false)\b', permissions[2])
    if len(values) != 0x69 or values[0x47] != 'false' or values[0x4d] != 'true':
        raise ValueError('pinned DS baseband permission bits differ')
    values[0x47], values[0x4d] = 'true', 'false'
    body = '\n' + '\n'.join('    ' + ', '.join(values[i:i+16]) + (',' if i+16 < len(values) else '')
                            for i in range(0, len(values), 16))
    text = text[:permissions.start(2)] + body + text[permissions.end(2):]
    # Support configuration readback and idle interrupt bookkeeping. Returning
    # 0xffff for real latches makes the SDK's hardware self-test fail.
    # GBATEK: W_IF is W1C; W_IF_SET excludes reserved bit 10; CPU IF.24
    # is raised only on a zero-to-nonzero transition of the enabled flags.
    replacements={
        'bool wifi_register_mapped(std::uint32_t offset) {':
        'std::uint32_t wifi_latch_mask(std::uint32_t offset) {\n'
        '    switch (offset & 0x1ffeu) {\n' + ''.join(
            f'    case 0x{address:03x}: return 0x{mask:04x}u;\n'
            for address,mask in MAC_LATCH_MASKS.items()) +
        '    default: return 0x10000u;\n    }\n}\n\n'
        'bool wifi_register_mapped(std::uint32_t offset) {\n'
        '    if (wifi_latch_mask(offset) <= 0xffffu) return true;',
        '    switch (offset & 0x1ffeu) {\n    case 0x158: return wifi.bb_read;':
        '    if (wifi_latch_mask(offset) <= 0xffffu) return wifi.mac_latches[(offset & 0x1ffeu) / 2];\n'
        '    switch (offset & 0x1ffeu) {\n    case 0x158: return wifi.bb_read;',
        '    switch (offset & 0x1ffeu) {\n    case 0x15a:':
        '    const auto mask = wifi_latch_mask(offset);\n'
        '    if (mask <= 0xffffu) { wifi.mac_latches[(offset & 0x1ffeu) / 2] = value & mask; return; }\n'
        '    switch (offset & 0x1ffeu) {\n    case 0x15a:',
        '    case 0x158: case 0x15a: case 0x15c: case 0x15e: case 0x168:':
        '    case 0x000: case 0x010: case 0x012: case 0x03c: case 0x040: case 0x19c: case 0x214: case 0x21c: case 0x2d0:\n    case 0x158: case 0x15a: case 0x15c: case 0x15e: case 0x168:',
        '    case 0x158: return wifi.bb_read;':
        '''    case 0x000: return 0x1440;
    case 0x010: return wifi.irq_flags;
    case 0x012: return wifi.irq_enable;
    case 0x03c: return wifi.power_state;
    case 0x040: return wifi.power_force;
    case 0x19c: return (wifi.power_state & 0x200u) ? 0x0046 : 0x0084;
    case 0x214: return (wifi.power_state & 0x200u) ? 9 : 1;
    case 0x2d0: return 0;
    case 0x21c: return 0;
    case 0x158: return wifi.bb_read;''',
        '    case 0x15a:\n        wifi.bb_write = value & 0xffu;':
        '''    case 0x010:
        wifi.irq_flags &= ~value;
        break;
    case 0x012:
        wifi.irq_enable = value;
        break;
    case 0x21c:
        wifi.irq_flags |= value & 0xfbffu;
        break;
    case 0x03c:
        if ((wifi.mac_latches[0x004/2] & 1u) && !(wifi.mac_latches[0x036/2] & 1u)) {
            if ((value & 2u) && (wifi.power_state & 0x200u)) {
                wifi.power_state = 0;
                wifi.irq_flags |= 1u << 11;
            } else wifi.power_state = (wifi.power_state & 0x300u) | (value & 3u);
        }
        break;
    case 0x040:
        if ((wifi.power_state & 0x100u) == 0) {
            wifi.power_force = value & 0x8001u;
            if (value & 0x8000u) {
                if (value & 1u) wifi.power_state = (wifi.power_state & 3u) | 0x200u;
                else if (wifi.power_state & 0x200u) wifi.power_state |= 0x100u;
            }
        }
        break;
    case 0x2d0:
        if ((wifi.power_state & 0x100u) && (value & 1u) == 0) {
            const bool was_off = (wifi.power_state & 0x200u) != 0;
            wifi.power_state = (wifi.power_state & 3u) | ((wifi.power_force & 1u) << 9);
            if (was_off && (wifi.power_state & 0x200u) == 0) wifi.irq_flags |= 1u << 11;
        }
        break;
    case 0x15a:
        wifi.bb_write = value & 0xffu;''',
        '''                const std::uint16_t merged =
                    merge16(old_value, reg_value, reg_addr, reg_width);
                wifi_write_register(wifi, reg_offset, merged);''':
        '''                const bool was_pending = (wifi.irq_flags & wifi.irq_enable) != 0;
                const bool command = (reg_offset & 0x1ffeu) == 0x010u ||
                                     (reg_offset & 0x1ffeu) == 0x21cu;
                const std::uint16_t merged = command
                    ? std::uint16_t(reg_width == 8 ? (reg_value & 0xffu) << ((reg_addr & 1u) * 8u) : reg_value)
                    : merge16(old_value, reg_value, reg_addr, reg_width);
                wifi_write_register(wifi, reg_offset, merged);
                if (!was_pending && (wifi.irq_flags & wifi.irq_enable) != 0) set_irq(1, 24);''',
    }
    for before,after in replacements.items():
        if text.count(before)!=1:
            raise ValueError('pinned DS wireless IRQ integration site differs')
        text=text.replace(before,after)
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
        '''        if (width == 8) return; // Wi-Fi STRB writes are ignored, including RAM.
        const std::uint32_t ram_offset = addr & 0x7fffu;
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
    text=text.replace(before,before+'    std::array<std::uint8_t, 0x2000> ram{};\n    std::array<std::uint16_t, 0x1000> mac_latches{};\n    std::uint16_t irq_flags = 0, irq_enable = 0;\n    std::uint16_t power_state = 0x200, power_force = 0;\n')
    before='    void reset() {\n        baseband.fill(0);'
    if text.count(before)!=1:raise ValueError('pinned DS wireless RAM reset differs')
    text=text.replace(before,'    void reset() {\n        ram.fill(0);\n        mac_latches.fill(0);\n        mac_latches[0x036/2] = 1;\n        mac_latches[0x050/2] = 0x4000;\n        mac_latches[0x052/2] = 0x4800;\n        mac_latches[0x122/2] = 0x4840;\n        mac_latches[0x130/2] = 0x0142;\n        mac_latches[0x132/2] = 0x8064;\n        mac_latches[0x134/2] = 0xffff;\n        mac_latches[0x142/2] = 0x2443;\n        irq_flags = irq_enable = 0;\n        power_state = 0x200; power_force = 0;\n        baseband.fill(0);')
    path.write_text(text,encoding='utf-8')
