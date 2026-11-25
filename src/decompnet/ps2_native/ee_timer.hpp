// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <cassert>
#include <cstdint>
#include <limits>
#include <utility>

namespace decomp_ps2::ee_timer
{
constexpr uint64_t never = std::numeric_limits<uint64_t>::max();

// The EE executor owns timer MMIO and guest cycle accounting.
template <class Memory>
struct State
{
    Memory *owner;
    uint64_t cycles = 0u;
    uint64_t deadline = never;
    bool materializing = false;

    void refresh() noexcept
    {
        materializing = true;
        deadline = owner->cyclesUntilNextEeTimerInterrupt();
        materializing = false;
    }

    uint32_t apply(uint64_t elapsed) noexcept
    {
        materializing = true;
        const uint32_t interrupts = owner->advanceEeTimers(elapsed);
        deadline = owner->cyclesUntilNextEeTimerInterrupt();
        materializing = false;
        return interrupts;
    }

    uint32_t advance(uint64_t elapsed) noexcept
    {
        if (elapsed > never - cycles)
        {
            const uint32_t prior = apply(std::exchange(cycles, 0u));
            return prior | apply(elapsed);
        }
        cycles += elapsed;
        if (deadline != never && cycles >= deadline)
            return apply(std::exchange(cycles, 0u));
        return 0u;
    }

    void flush() noexcept
    {
        if (cycles != 0u)
        {
            const uint32_t interrupts = apply(std::exchange(cycles, 0u));
            assert(interrupts == 0u && "Deferred timer missed its IRQ deadline");
            (void)interrupts;
        }
    }
};

template <class Memory>
inline thread_local State<Memory> *active = nullptr;

template <class Memory>
State<Memory> *stateFor(const Memory *owner) noexcept
{
    auto *state = active<Memory>;
    return state && state->owner == owner && !state->materializing ? state : nullptr;
}

template <class Memory>
class Session
{
public:
    Session(Memory &memory, bool enabled) noexcept : m_state{&memory}
    {
        if (enabled && !active<Memory>)
        {
            m_state.refresh();
            active<Memory> = &m_state;
        }
    }

    Session(const Session &) = delete;
    Session &operator=(const Session &) = delete;

    ~Session() { finish(); }

    void finish() noexcept
    {
        if (active<Memory> != &m_state)
            return;
        m_state.flush();
        active<Memory> = nullptr;
    }

private:
    State<Memory> m_state;
};
}
