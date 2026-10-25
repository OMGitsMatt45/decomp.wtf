// SPDX-License-Identifier: MIT
#include "anygba/system.hpp"

namespace anygba {
// Synchronize peripheral reads without delivering an IRQ in the middle of an
// instruction. Normal end-of-instruction tick() performs interrupt delivery.
void System::memory_load_events() { run_events(); }
}
extern "C" void anygba_load_events(anygba_cpu* c) {
    anygba::system_of(c).memory_load_events();
}
