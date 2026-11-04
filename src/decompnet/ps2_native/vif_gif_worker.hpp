// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <array>
#include <cfenv>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <new>
#include <stdexcept>
#include <thread>
#include <utility>

#if defined(_M_X64) || defined(__x86_64__)
#include <xmmintrin.h>
#endif

namespace decomp_ps2::vif_gif {

// Only the native runtime installs this target. A general std::function
// may inspect GS state or call a presenter and must execute inline.
template <class... Args>
struct RuntimeVuCallback
{
    const void *memory;
    void *runtime;
    void (*call)(void *, Args...);
    void operator()(Args... args) const { call(runtime, args...); }
};

using RuntimeMscal = RuntimeVuCallback<uint32_t, uint32_t, uint32_t>;
using RuntimeMscnt = RuntimeVuCallback<uint32_t, uint32_t>;

template <class Target, class Function>
bool isRuntimeVuCallback(const Function &function, const void *memory)
{
    if (!function)
        return true;
    const auto *target = function.template target<Target>();
    return target && target->memory == memory;
}

struct FloatControl
{
    unsigned value;

    static FloatControl capture()
    {
#if defined(_M_X64) || defined(__x86_64__)
        return {_mm_getcsr() & 0xFFC0u};
#else
        return {static_cast<unsigned>(std::fegetround())};
#endif
    }

    bool supported() const
    {
#if defined(_M_X64) || defined(__x86_64__)
        // A trap must remain on the thread that executed the guest operation.
        return (value & 0x1F80u) == 0x1F80u;
#else
        return value == FE_TONEAREST || value == FE_DOWNWARD || value == FE_UPWARD || value == FE_TOWARDZERO;
#endif
    }

    void apply() const
    {
#if defined(_M_X64) || defined(__x86_64__)
        constexpr int modes[] = {FE_TONEAREST, FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO};
        const int rounding = modes[(value >> 13u) & 3u];
#else
        const int rounding = static_cast<int>(value);
#endif
        if (std::fesetround(rounding) != 0)
            throw std::runtime_error("GIF mailbox could not match producer rounding");
#if defined(_M_X64) || defined(__x86_64__)
        _mm_setcsr((_mm_getcsr() & 0x3Fu) | value);
#endif
    }
};

class Pump
{
public:
    using Sink = void (*)(void *, const uint8_t *, uint32_t);

    Pump()
    {
        for (size_t i = 0; i < kSlots; ++i)
            m_free[i] = i;
        m_thread = std::thread([this] { run(); });
    }
    Pump(const Pump &) = delete;
    Pump &operator=(const Pump &) = delete;
    ~Pump()
    {
        try { fence(); } catch (...) {}
        {
            std::lock_guard lock(m_mutex);
            m_stop = true;
        }
        m_ready.notify_one();
        m_thread.join();
    }

    bool trySubmit(void *target, Sink sink, const uint8_t *data, uint32_t size)
    {
        const auto control = FloatControl::capture();
        if (!data || size == 0u || size > kBatchBytes || !control.supported())
            return false;
        if (m_current != kSlots)
        {
            const auto &batch = m_slots[m_current];
            if (batch.target != target || batch.sink != sink || batch.control.value != control.value ||
                size > kBatchBytes - batch.used)
                publish();
        }
        if (m_current == kSlots && !acquire())
            return false;

        auto &batch = m_slots[m_current];
        batch.target = target;
        batch.sink = sink;
        batch.control = control;
        std::memcpy(batch.data.get() + batch.used, data, size);
        batch.spans[batch.count++] = {batch.used, size};
        batch.used += size;
        if (batch.count == batch.spans.size() || batch.used >= kPublishBytes)
            publish();
        return true;
    }

    void fence()
    {
        publish();
        std::unique_lock lock(m_mutex);
        m_released.wait(lock, [this] { return m_inFlight == 0u; });
        if (m_error)
            std::rethrow_exception(m_error);
    }

private:
    static constexpr size_t kSlots = 16;
    static constexpr uint32_t kBatchBytes = 512u * 1024u;
    static constexpr uint32_t kPublishBytes = 128u * 1024u;
    struct Span { uint32_t offset, size; };
    struct Batch
    {
        std::unique_ptr<uint8_t[]> data;
        std::array<Span, 256> spans;
        void *target = nullptr;
        Sink sink = nullptr;
        FloatControl control{};
        uint32_t used = 0u;
        uint32_t count = 0u;
    };

    bool acquire()
    {
        size_t index;
        {
            std::unique_lock lock(m_mutex);
            m_released.wait(lock, [this] { return m_freeCount != 0u || m_error; });
            if (m_error)
                std::rethrow_exception(m_error);
            index = m_free[--m_freeCount];
        }
        auto &batch = m_slots[index];
        if (!batch.data)
        {
            batch.data.reset(new (std::nothrow) uint8_t[kBatchBytes]);
            if (!batch.data)
            {
                std::lock_guard lock(m_mutex);
                m_free[m_freeCount++] = index;
                return false;
            }
        }
        m_current = index;
        return true;
    }

    void publish()
    {
        if (m_current == kSlots)
            return;
        {
            std::lock_guard lock(m_mutex);
            m_pending[(m_pendingFirst + m_pendingCount++) % kSlots] = m_current;
            ++m_inFlight;
            m_current = kSlots;
        }
        m_ready.notify_one();
    }

    void run()
    {
        unsigned installed = ~0u;
        for (;;)
        {
            size_t index;
            bool discard;
            {
                std::unique_lock lock(m_mutex);
                m_ready.wait(lock, [this] { return m_stop || m_pendingCount != 0u; });
                if (!m_pendingCount)
                    return;
                index = m_pending[m_pendingFirst];
                m_pendingFirst = (m_pendingFirst + 1u) % kSlots;
                --m_pendingCount;
                discard = static_cast<bool>(m_error);
            }
            auto &batch = m_slots[index];
            std::exception_ptr error;
            if (!discard)
                try
                {
                    if (installed != batch.control.value)
                    {
                        batch.control.apply();
                        installed = batch.control.value;
                    }
                    for (size_t i = 0; i < batch.count; ++i)
                    {
                        const auto span = batch.spans[i];
                        batch.sink(batch.target, batch.data.get() + span.offset, span.size);
                    }
                }
                catch (...) { error = std::current_exception(); }
            batch.used = batch.count = 0u;
            {
                std::lock_guard lock(m_mutex);
                if (error)
                    m_error = error;
                m_free[m_freeCount++] = index;
                --m_inFlight;
            }
            m_released.notify_one();
        }
    }

    std::array<Batch, kSlots> m_slots;
    std::array<size_t, kSlots> m_free, m_pending;
    std::mutex m_mutex;
    std::condition_variable m_ready, m_released;
    std::thread m_thread;
    std::exception_ptr m_error;
    size_t m_current = kSlots, m_freeCount = kSlots, m_pendingFirst = 0, m_pendingCount = 0, m_inFlight = 0;
    bool m_stop = false;
};

class Scope;
class ThreadSession;
inline thread_local ThreadSession *currentSession = nullptr;
inline thread_local Scope *activeScope = nullptr;
inline thread_local std::mutex *ownedBoundary = nullptr;

// One session belongs to the guest producer thread. The worker joins before
// that thread exits, while the GS and its backend are still alive.
class ThreadSession
{
public:
    ThreadSession(const void *memory, const void *arbiter, std::mutex *boundary)
        : m_memory(memory), m_arbiter(arbiter), m_boundary(boundary)
    {
#if defined(_M_X64) || defined(__x86_64__)
        if (boundary && !currentSession)
            currentSession = this;
#endif
    }
    ThreadSession(const ThreadSession &) = delete;
    ThreadSession &operator=(const ThreadSession &) = delete;
    ~ThreadSession()
    {
        if (currentSession == this)
            currentSession = nullptr;
    }

private:
    friend class Scope;
    Pump *pump()
    {
        if (!m_pump && !m_unavailable)
        {
            try { m_pump = std::make_unique<Pump>(); }
            catch (const std::exception &) { m_unavailable = true; }
        }
        return m_pump.get();
    }

    const void *m_memory;
    const void *m_arbiter;
    std::mutex *m_boundary;
    std::unique_ptr<Pump> m_pump;
    bool m_unavailable = false;
};

class Scope
{
public:
    Scope(const void *memory, const void *arbiter, bool compatible,
          bool (*check)(const void *, const std::mutex *))
    {
        if (activeScope)
        {
            // A nested interpretation runs inline at a complete packet boundary.
            activeScope->fence();
            m_parent = std::exchange(activeScope, nullptr);
            return;
        }
        auto *session = currentSession;
        if (!compatible || ownedBoundary || !session ||
            session->m_memory != memory || session->m_arbiter != arbiter)
            return;
        m_boundary = std::unique_lock(*session->m_boundary);
        if (check(arbiter, session->m_boundary))
            m_pump = session->pump();
        if (!m_pump)
        {
            m_boundary.unlock();
            return;
        }
        m_arbiter = arbiter;
        ownedBoundary = session->m_boundary;
        activeScope = this;
    }
    Scope(const Scope &) = delete;
    Scope &operator=(const Scope &) = delete;
    ~Scope() { try { finish(); } catch (...) {} }

    bool owns(const void *arbiter) const { return m_arbiter == arbiter; }
    bool matches(const void *arbiter, const std::mutex *boundary) const
    {
        return owns(arbiter) && m_boundary.mutex() == boundary;
    }
    bool trySubmit(void *target, Pump::Sink sink, const uint8_t *data, uint32_t size)
    {
        return m_pump->trySubmit(target, sink, data, size);
    }
    void fence()
    {
        if (m_pump)
            m_pump->fence();
    }
    void finish()
    {
        if (m_parent)
            activeScope = std::exchange(m_parent, nullptr);
        if (auto *pump = std::exchange(m_pump, nullptr))
        {
            activeScope = nullptr;
            ownedBoundary = nullptr;
            auto boundary = std::move(m_boundary);
            pump->fence();
        }
    }

private:
    const void *m_arbiter = nullptr;
    Pump *m_pump = nullptr;
    Scope *m_parent = nullptr;
    std::unique_lock<std::mutex> m_boundary;
};

inline std::unique_lock<std::mutex> lockPresentation(std::mutex &boundary, bool enabled)
{
    if (!enabled)
        return {};
    if (ownedBoundary == &boundary)
    {
        if (activeScope)
            activeScope->fence();
        return {};
    }
    return std::unique_lock(boundary);
}

inline bool overlaps(const uint8_t *data, uint32_t size, const void *storage, size_t storageSize)
{
    const auto address = reinterpret_cast<uintptr_t>(data);
    const auto base = reinterpret_cast<uintptr_t>(storage);
    return storage && (address >= base ? address - base < storageSize : base - address < size);
}

}
