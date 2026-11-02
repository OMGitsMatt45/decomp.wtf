"""Latch retail B7 addresses after capacity masking and protected-area mapping."""
from pathlib import Path


def patch(root):
    path = Path(root)/'runtime/periph/src/periph.cpp'
    text = path.read_text(encoding='utf-8')
    changes = {
        'enum class TransferKind : std::uint8_t { None, Rom, Special, Fill };':
        'enum class TransferKind : std::uint8_t { None, Rom, RetailRom, Special, Fill };',
        '        if (transfer_kind_ == TransferKind::Rom)\n':
        '''        if (transfer_kind_ == TransferKind::RetailRom) {
            // A retail data stream wraps within its latched 4 KiB page.
            const std::uint32_t at = (transfer_rom_address_ & ~0xfffu) |
                ((transfer_rom_address_ + static_cast<std::uint32_t>(transfer_pos_)) & 0xfffu);
            return rom_data_byte(at);
        }
        if (transfer_kind_ == TransferKind::Rom)
''',
        '''        case 0xb7: {
            transfer_kind_ = TransferKind::Rom;
            // Low B7 reads repeat the first protected 0x200-byte block.
''':
        '''        case 0xb7: {
            transfer_kind_ = TransferKind::RetailRom;
            // Missing address lines mirror the cartridge before low-address
            // protection is applied. Retain unmapped padding in trimmed images.
            std::uint64_t capacity = 1;
            while (capacity < rom_size_) capacity <<= 1;
            if (rom_size_ > 0x14 && rom_[0x14] <= 15) {
                const std::uint64_t declared = std::uint64_t{0x20000} << rom_[0x14];
                capacity = std::max(capacity, declared);
            }
            transfer_rom_address_ &= static_cast<std::uint32_t>(capacity - 1);
            // Low B7 reads repeat the first protected 0x200-byte block.
''',
    }
    for before, after in changes.items():
        if text.count(before) != 1:
            raise ValueError('Pinned retail cartridge integration differs')
        text = text.replace(before, after, 1)
    path.write_text(text, encoding='utf-8')
