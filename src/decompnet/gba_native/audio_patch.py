"""Optional band-limited DirectSound presentation; hardware state stays unchanged."""


def apply(destination, source):
    def patch(path, old, new):
        target = destination / path
        text = target.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise RuntimeError(f'GBA enhanced audio patch no longer applies: {path}: {old!r}')
        target.write_text(text.replace(old, new), encoding='utf-8')

    (destination/'runtime/include/anygba/audio_interpolator.hpp').write_text(
        source('audio_interpolator.hpp'), encoding='utf-8')
    patch('runtime/include/anygba/system.hpp', 'struct Options {',
          'struct Options {\n    bool enhanced_audio = false;')
    patch('runtime/include/anygba/system.hpp', 'const Options& options() const { return options_; }',
          'const Options& options() const { return options_; }\n'
          '    void set_enhanced_audio(bool enabled) { options_.enhanced_audio = enabled; }')
    patch('runtime/src/apu/apu.h', '#include "anygba/system.hpp"',
          '#include "anygba/system.hpp"\n#include "anygba/audio_interpolator.hpp"')
    patch('runtime/src/apu/apu.h', '        bool fed = false;',
          '        AudioInterpolator interpolation;\n        bool fed = false;')
    patch('runtime/src/apu/apu.h', '            read = size = 0;',
          '            interpolation.reset();\n            read = size = 0;')
    patch('runtime/src/apu/fifo.cpp', '        if (fifo.size <= 16) {',
          '        fifo.interpolation.push(fifo.current, at);\n        if (fifo.size <= 16) {')
    patch('runtime/src/apu/mixer.cpp',
          '            const double sample = fifo_[f].current * ((cnt_h & (4u << f)) ? 4.0 : 2.0);',
          '''            double value = fifo_[f].current;
            const auto timer = (cnt_h >> (f == 0 ? 10 : 14)) & 1;
            if (sys_.options().enhanced_audio && (reg(0x102 + timer * 4) & 0x80)) {
                std::array<std::int8_t, 8> future{};
                const auto& fifo = fifo_[f];
                const auto count = std::min(fifo.size, unsigned(future.size()));
                for (unsigned i = 0; i < count; ++i)future[i] = fifo.data[(fifo.read + i) % fifo.data.size()];
                value = fifo.interpolation.sample(next_sample_, {future.data(), count}, value);
            }
            const double sample = value * ((cnt_h & (4u << f)) ? 4.0 : 2.0);''')
    patch('runtime/src/state/state.cpp', '    for (Fifo& f : fifo_) {',
          '    for (Fifo& f : fifo_) {\n        if (ar.loading()) f.interpolation.reset();')
