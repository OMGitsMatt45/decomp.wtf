"""Install opt-in deferred EE timer accounting on the pinned runtime."""
from pathlib import Path
import re

from .runtime_patch import replace


HEADER = "decomp_ee_timer.hpp"
NS = "decomp_ps2::ee_timer"


def split_eager_body(memory):
    text = memory.read_text(encoding="utf-8")
    signature = "uint32_t PS2Memory::advanceEeTimers(uint64_t eeCycles) noexcept"
    first_eager_line = "    uint32_t interruptMask = 0u;"
    next_method = "\n}\n\nuint64_t PS2Memory::cyclesUntilNextEeTimerInterrupt()"
    start = text.index(signature)
    first = text.index(first_eager_line, start)
    end = text.index(next_method, first)
    body = text[first:end].replace("m_eeTimers", "timers")
    if body.count("EeTimer &timer") != 1:
        raise ValueError("Pinned eager EE timer iterator changed")
    body = body.replace("EeTimer &timer", "auto &timer")
    helper = """namespace
{
template <class Timers>
#if defined(_MSC_VER)
__declspec(noinline)
#elif defined(__GNUC__)
__attribute__((noinline))
#endif
uint32_t advanceEeTimersEager(Timers &timers, uint64_t eeCycles) noexcept
{
""" + body + """
}
}

"""
    old = text[start:end]
    wrapper = text[start:first] + "    return advanceEeTimersEager(m_eeTimers, eeCycles);"
    replace(memory, old, helper + wrapper)


def patch_memory(memory):
    replace(memory, '#include "runtime/ps2_memory.h"',
            f'#include "runtime/ps2_memory.h"\n#include "{HEADER}"')
    replace(memory, """    m_eeTimers = {};
    m_anyEeTimerCued = false;""", f"""    m_eeTimers = {{}};
    m_anyEeTimerCued = false;
    if (auto *deferred = {NS}::stateFor(this))
    {{
        deferred->cycles = 0u;
        deferred->deadline = {NS}::never;
    }}""")

    split_eager_body(memory)
    eager_call = "    return advanceEeTimersEager(m_eeTimers, eeCycles);"
    replace(memory, eager_call, f"""    if (auto *deferred = {NS}::stateFor(this))
        return deferred->advance(eeCycles);

{eager_call}""")

    deadline = "uint64_t PS2Memory::cyclesUntilNextEeTimerInterrupt() const noexcept\n{"
    replace(memory, deadline, deadline + f"""
    if (const auto *deferred = {NS}::stateFor(this))
        return deferred->deadline == {NS}::never
            ? deferred->deadline : deferred->deadline - deferred->cycles;""")

    read = "        const EeTimer &timer = m_eeTimers[timerIndex];"
    replace(memory, read, f"""        if (auto *deferred = {NS}::stateFor(this))
            deferred->flush();
{read}""")
    write = "        EeTimer &timer = m_eeTimers[timerIndex];"
    replace(memory, write, f"""        auto *deferred = {NS}::stateFor(this);
        if (deferred)
            deferred->flush();
{write}""")
    end_write = """        case kEeTimerHoldOffset:
            timer.hold = value & 0xFFFFu;
            break;
        default:
            return false;
        }
        return true;"""
    replace(memory, end_write, end_write.replace("        return true;",
            "        if (deferred)\n            deferred->refresh();\n        return true;"))


def patch_scheduler(scheduler):
    include = '#include "runtime/ee_scheduler.h"'
    replace(scheduler, include, include + f'\n#include "../{HEADER}"')
    text = scheduler.read_text(encoding="utf-8")
    anchor = "void EeScheduler::run()\n{\n    assertExecutor();"
    start = text.index(anchor)
    end = text.index("\nvoid EeScheduler::requestStop()", start)
    original = text[start:end]
    modified, exits = re.subn(r"(?m)^( *)m_running\.store\(false, std::memory_order_release\);$",
                             r"\1timerSession.finish();\n\g<0>", original)
    if exits != 3:
        raise ValueError("Pinned EE scheduler's exit publication paths changed")
    modified = modified.replace(anchor, anchor + f"""
    const char *deferredTimers = std::getenv("DECOMP_PS2_DEFERRED_EE_TIMERS");
    {NS}::Session timerSession(m_runtime.memory(),
                                 deferredTimers && std::strcmp(deferredTimers, "1") == 0);""")
    replace(scheduler, original, modified)


def patch(root):
    sources = Path(root) / "thirdparty/PS2Recomp/ps2xRuntime/src/lib"
    (sources / HEADER).write_bytes(Path(__file__).with_name("ee_timer.hpp").read_bytes())
    patch_memory(sources / "ps2_memory.cpp")
    patch_scheduler(sources / "Kernel/EeScheduler.cpp")
