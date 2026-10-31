// SPDX-License-Identifier: MIT
// Project-owned native replacements, including direct compiled call sites.
#include "anygba/system.hpp"

namespace anygba {
void System::set_native_entry_hook(uint32_t address,bool thumb,std::function<bool(System&)> hook) {
    if(address<0x08000000||address>=0x0a000000||(address&(thumb?1u:3u)))
        throw Error("native entry hooks require an aligned canonical cartridge address");
    const auto key=std::pair{address,thumb};
    if(hook)native_entry_hooks_[key]=std::move(hook);else native_entry_hooks_.erase(key);
    cpu_.native_hooks=!native_entry_hooks_.empty();
}
bool System::intercept_native_entry(uint32_t address,bool thumb) {
    const auto it=native_entry_hooks_.find({address,thumb});
    return it!=native_entry_hooks_.end()&&it->second(*this);
}
}
extern "C" int anygba_native_entry_hook(anygba_cpu* cpu,uint32_t address) {
    return static_cast<anygba::System*>(cpu->runtime)->intercept_native_entry(address,cpu->t!=0);
}
