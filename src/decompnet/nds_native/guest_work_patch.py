"""Owner-thread native callbacks at interruptible guest CPU checkpoints."""
from pathlib import Path
from .capture_patch import replace


def patch(root):
    root=Path(root)
    p=root/'runtime/include/dsr/machine.h'
    s=replace(p.read_text(),'#include <filesystem>','#include <filesystem>\n#include <functional>')
    s=replace(s,'    void start_cpu(CpuId id, std::uint32_t entry);','''    void start_cpu(CpuId id, std::uint32_t entry);

    // Enqueue from this machine's owning host thread. Work runs on the CPU's
    // guest fiber at an interruptible user/system checkpoint, after pending
    // IRQs. It may call translated SDK code and yield; architectural state is
    // restored on completion, while charged cycles and memory writes remain.
    // No callback runs in an IRQ or with CPSR.I set. FIFO order is preserved;
    // reentrant execution is prevented across guest thread switches. Up to 64
    // pending callbacks per CPU. Captured data must outlive execution/reset.
    // Exceptions are rethrown by run_ticks/run_frame on the host stack.
    void post_guest_work(CpuId id, std::function<void(Cpu&)> work);''')
    p.write_text(s)
    p=root/'runtime/core/src/core_internal.h'
    s=replace(p.read_text(),'struct CpuRuntime {','''struct CpuRuntime {
    std::deque<std::function<void(Cpu&)>> guest_work;
    std::exception_ptr guest_work_failure;
    bool guest_work_active = false;''')
    s=replace(s,'#pragma once','#pragma once\n#include <deque>\n#include <exception>\n#include <functional>')
    s=replace(s,'    void checkpoint(Cpu* cpu, std::uint32_t pc);','''    void checkpoint(Cpu* cpu, std::uint32_t pc);
    void perform_guest_work(CpuRuntime& runtime);''')
    p.write_text(s)
    p=root/'runtime/core/src/machine.cpp'
    s=replace(p.read_text(),'        rt.fiber_done = false;','''        rt.fiber_done = false;
        rt.guest_work.clear();
        rt.guest_work_failure = nullptr;
        rt.guest_work_active = false;''')
    s=replace(s,'void Machine::raise_irq(CpuId id, unsigned irq)', '''void Machine::post_guest_work(CpuId id, std::function<void(Cpu&)> work) {
    auto& rt=impl_->runtime(id);
    if(!work)throw std::invalid_argument("Guest work callback is empty");
    if(rt.guest_work_failure)std::rethrow_exception(rt.guest_work_failure);
    if(rt.guest_work.size()>=64)throw std::length_error("Guest work queue is full");
    rt.guest_work.push_back(std::move(work));
    rt.force_irq_checkpoint();
}

void Machine::raise_irq(CpuId id, unsigned irq)''')
    p.write_text(s)
    p=root/'runtime/core/src/scheduler.cpp'
    s=replace(p.read_text(),'''    if (rt.fiber_done || rt.stopped || rt.entry == 0) return;''','''    if(rt.guest_work_failure)std::rethrow_exception(rt.guest_work_failure);
    if (rt.fiber_done || rt.stopped || rt.entry == 0) return;''')
    s=replace(s,'    if (rt.active_fiber->finished()) {','''    if(rt.guest_work_failure)std::rethrow_exception(rt.guest_work_failure);
    if (rt.active_fiber->finished()) {''')
    s=replace(s,'void Machine::Impl::checkpoint(Cpu* cpu, std::uint32_t pc) {','''void Machine::Impl::perform_guest_work(CpuRuntime& rt) {
    auto& cpu=rt.cpu;
    const auto mode=cpu.cpsr_ctrl&kCpsrModeMask;
    if(rt.guest_work.empty()||rt.guest_work_active||rt.guest_work_failure||rt.in_irq||
       (cpu.cpsr_ctrl&kCpsrI)||(mode!=kModeSys&&mode!=kModeUsr))return;
    auto work=std::move(rt.guest_work.front());rt.guest_work.pop_front();
    const auto saved=cpu;const auto cpsr=rt.banks.cpsr(cpu);
    const auto pc=rt.current_pc;
    rt.guest_work_active=true;
    try{work(cpu);}catch(...){rt.guest_work_failure=std::current_exception();}
    // A nested SDK call may yield or switch to another guest thread. Restore
    // only this suspended caller's architectural state, never its old budget.
    rt.banks.write_cpsr(cpu,cpsr,0xf);
    std::copy(std::begin(saved.r),std::end(saved.r),std::begin(cpu.r));
    rt.current_pc=pc;
    rt.guest_work_active=false;
}

void Machine::Impl::checkpoint(Cpu* cpu, std::uint32_t pc) {''')
    s=replace(s,'    if (cpu->budget <= 0) {\n        Fiber::yield();','''    perform_guest_work(rt);
    if (cpu->budget <= 0) {
        Fiber::yield();''')
    s=replace(s,'''        if (can_deliver_irq(static_cast<unsigned>(cpu->id))) enter_irq(rt, pc);
    }
}

void Machine::Impl::halt''','''        if (can_deliver_irq(static_cast<unsigned>(cpu->id))) enter_irq(rt, pc);
        perform_guest_work(rt);
    }
}

void Machine::Impl::halt''')
    p.write_text(s)
