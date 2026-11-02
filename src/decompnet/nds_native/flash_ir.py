"""Support IR-cartridge savedata framing and firmware identification."""
from pathlib import Path


def patch(root):
    path=Path(root)/'runtime/periph/src/periph.cpp';text=path.read_text(encoding='utf-8')
    changes={
        '        backup_command_ = 0xff;\n        backup_stage_ = BackupStage::Command;':
        '        backup_command_ = 0xff;\n        backup_ir_prefixed_ = false;\n        backup_stage_ = BackupStage::Command;',
        '        if (backup_stage_ == BackupStage::Command) {\n            backup_command_ = value;':
        '''        if (backup_stage_ == BackupStage::Command) {
            // GBATEK: I-prefixed cartridge codes route 00h,cmd,... to savedata.
            // NEW IR firmware also answers 08h,ver with ver=AAh.
            if (!backup_ir_prefixed_ && rom_size_ > 0x0c && rom_[0x0c] == 'I') {
                if (value == 0) {
                    backup_ir_prefixed_ = true;
                    return 0xff;
                }
                if (value == 8) {
                    backup_stage_ = BackupStage::IrVersion;
                    return 0xff;
                }
            }
            backup_command_ = value;''',
        '    std::uint8_t aux_data_ = 0xff;':
        '    bool backup_ir_prefixed_ = false;\n    std::uint8_t aux_data_ = 0xff;',
        '        case BackupStage::Status:':
        '        case BackupStage::IrVersion:\n            return 0xaa;\n        case BackupStage::Status:',
        '    enum class BackupStage : std::uint8_t {\n        Command, Address, Dummy, Read, Write, WriteStatus, Status, Id, Ignore':
        '    enum class BackupStage : std::uint8_t {\n        Command, Address, Dummy, Read, Write, WriteStatus, Status, Id, Ignore, IrVersion',
    }
    for before,after in changes.items():
        if text.count(before)!=1:raise ValueError('pinned IR backup integration differs')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
