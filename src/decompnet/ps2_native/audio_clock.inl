// SPDX-License-Identifier: MIT
// Included in the pinned raylib audio translation unit.
bool decompAudioClockSupported(void)
{
#if defined(SUPPORT_MODULE_RAUDIO)
    return true;
#else
    return false;
#endif
}

bool decompSetAudioStreamClockRate(AudioStream stream, double rate,
                                  void (*commit)(void *, double), void *context)
{
#if defined(SUPPORT_MODULE_RAUDIO)
    rAudioBuffer *buffer = stream.buffer;
    if (!buffer || !commit || !(rate >= 0.5 && rate <= 2.0)) return false;

    // The caller owns the stream until this returns. The commit only changes
    // the matching guest clock and must never call an audio API.
    ma_mutex_lock(&AUDIO.System.lock);
    const ma_uint32 nominal = buffer->converter.sampleRateOut;
    const ma_uint32 output = (ma_uint32)(nominal / rate + 0.5);
    const bool changed = output && ma_data_converter_set_rate(
        &buffer->converter, buffer->converter.sampleRateIn, output) == MA_SUCCESS;
    if (changed)
    {
        const double effectiveRate = (double)nominal / output;
        buffer->pitch = (float)effectiveRate;
        commit(context, effectiveRate);
    }
    ma_mutex_unlock(&AUDIO.System.lock);
    return changed;
#else
    (void)stream;
    (void)rate;
    (void)commit;
    (void)context;
    return false;
#endif
}
