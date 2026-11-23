"""Add an optional paced native IOP audio stream to the copied PS2 runtime."""

from pathlib import Path


def patch(root, replace):
    runtime = Path(root) / 'thirdparty/PS2Recomp/ps2xRuntime'
    header = runtime / 'include/runtime/ps2_native_iop.h'
    source = runtime / 'src/lib/ps2_native_iop.cpp'
    replace(header, '    void setPaused(bool paused);', '''    void setPaused(bool paused);

    // Address the owning desktop runtime only. Rate 1 restores real time.
    // An unsupported audio backend or a paused stream cannot be accelerated.
    bool hasHostClockRate();
    bool setHostClockRate(PS2Runtime &runtime, double rate);''')
    replace(source, '#include "ps2_iop_transport.h"', '''#include "ps2_iop_transport.h"
#include "ps2_runtime.h"
#include "runtime/ee_scheduler.h"''')
    replace(source, 'namespace ps2_native_iop', '''#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK) && !defined(PLATFORM_VITA)
extern "C" bool decompAudioClockSupported(void);
extern "C" bool decompSetAudioStreamClockRate(AudioStream stream, double rate,
                                            void (*commit)(void *, double), void *context);
#endif

namespace ps2_native_iop''')
    replace(source, '        bool g_paused = false;', '''        bool g_paused = false;
#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK) && !defined(PLATFORM_VITA)
        PS2Runtime *g_clockOwner = nullptr;
        bool g_clockOverridden = false;

        // Both callers and stream teardown hold g_streamMutex. The mixer
        // transaction can then update the media clock without losing a sample.
        bool setClockRateLocked(double rate)
        {
            const bool changed = decompSetAudioStreamClockRate(g_stream, rate,
                [](void *context, double effectiveRate) {
                    static_cast<PS2Runtime *>(context)->eeScheduler().setHostSpeed(effectiveRate);
                }, g_clockOwner);
            if (changed)
                g_clockOverridden = rate != 1.0;
            return changed;
        }
#endif''')
    replace(source, '        if (paused)\n            PauseAudioStream(g_stream);', '''        if (paused) {
#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK)
            if (g_clockOverridden)
                setClockRateLocked(1.0);
#endif
            PauseAudioStream(g_stream);
        }''')
    replace(source, '        g_streaming = true;', '''#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK)
        g_clockOwner = &runtime;
#endif
        g_streaming = true;''')
    replace(source, '    void stopAudio()', '''    bool hasHostClockRate()
    {
#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK) && !defined(PLATFORM_VITA)
        return decompAudioClockSupported();
#else
        return false;
#endif
    }

    bool setHostClockRate(PS2Runtime &runtime, double rate)
    {
#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK) && !defined(PLATFORM_VITA)
        if (!(rate >= 0.5 && rate <= 2.0))
            return false;
        std::lock_guard lock(g_streamMutex);
        if (!g_streaming)
            return false;
        if (g_clockOwner != &runtime || (rate != 1.0 && (g_paused || runtime.eeScheduler().hostPaused())))
            return false;
        return setClockRateLocked(rate);
#else
        (void)runtime;
        (void)rate;
        return false;
#endif
    }

    void stopAudio()''')
    replace(source, '        UnloadAudioStream(g_stream);', '''#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK)
        const bool restored = !g_clockOverridden || setClockRateLocked(1.0);
#endif
        UnloadAudioStream(g_stream);
#if defined(DECOMP_PS2_NATIVE_AUDIO_CLOCK)
        if (!restored)
            g_clockOwner->eeScheduler().setHostSpeed(1.0);
        g_clockOwner = nullptr;
        g_clockOverridden = false;
#endif''')
