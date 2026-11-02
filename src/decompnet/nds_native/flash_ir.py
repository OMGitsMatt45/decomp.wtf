"""Support the documented IR-cartridge savedata pass-through prefix."""
from pathlib import Path


def patch(root):
    path=Path(root)/'runtime/periph/src/periph.cpp';text=path.read_text(encoding='utf-8')
    changes={
        '        backup_command_ = 0xff;\n        backup_stage_ = BackupStage::Command;':
        '        backup_command_ = 0xff;\n        backup_ir_prefixed_ = false;\n        backup_stage_ = BackupStage::Command;',
        '        if (backup_stage_ == BackupStage::Command) {\n            backup_command_ = value;':
        '''        if (backup_stage_ == BackupStage::Command) {
            // GBATEK: I-prefixed cartridge codes route 00h,cmd,... to savedata.
            // Retain the existing direct-chip path; IR packet transport is separate.
            if (!backup_ir_prefixed_ && rom_size_ > 0x0c && rom_[0x0c] == 'I' && value == 0) {
                backup_ir_prefixed_ = true;
                return 0xff;
            }
            backup_command_ = value;''',
        '    std::uint8_t aux_data_ = 0xff;':
        '    bool backup_ir_prefixed_ = false;\n    std::uint8_t aux_data_ = 0xff;',
    }
    for before,after in changes.items():
        if text.count(before)!=1:raise ValueError('pinned IR backup integration differs')
        text=text.replace(before,after)
    path.write_text(text,encoding='utf-8')
