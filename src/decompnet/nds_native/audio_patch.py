"""Optional host audio cleanup; preserve hardware samples and capture timing."""
from pathlib import Path
from .capture_patch import replace


HEADER = '''    // Presentation only. Hardware remains the default for reference runs.
    // Clean keeps 16-bit output and linearly reconstructs sampled instruments.
    // Channel events, registers and sound-capture RAM use the hardware path.
    enum class OutputQuality { Hardware, Clean };
    void set_output_quality(OutputQuality quality);

'''

AUDIBLE = '''    std::int32_t audible_channel(unsigned n) const {
        const Channel& c=ch[n];
        if(quality!=Spu::OutputQuality::Clean || !c.busy || ((c.cnt>>29U)&3U)==3U)
            return output_channel(n);
        // Causal interpolation uses only samples already fetched by the DS.
        // No speculative reads, ADPCM lookahead, extra channel events or buffers.
        const auto p=period(c,n);
        const auto phase=std::min<std::uint64_t>(now-c.origin,p);
        const auto delta=std::int64_t(c.current)-c.previous;
        const auto rounded=delta*std::int64_t(phase)+(delta>=0?std::int64_t(p/2):-std::int64_t(p/2));
        const auto sample=c.previous+std::int32_t(rounded/std::int64_t(p));
        const unsigned div=(c.cnt>>8U)&3U,shift=div==3U?4U:div;
        return scale7(sample,c.cnt&127U)>>shift;
    }
'''

OUTPUT = '''        int l,r;
        if(quality==Spu::OutputQuality::Clean) {
            // Keep the DS bias/saturation range, retaining the low six bits
            // that its physical DAC discards. No gain boost or loudness filter.
            const int center=static_cast<int>(bias)*64;
            l=std::clamp(left+center,0,65535)-center;
            r=std::clamp(right+center,0,65535)-center;
        } else {
            left>>=6U; right>>=6U;
            left=std::clamp(left+static_cast<std::int32_t>(bias),0,1023)-static_cast<std::int32_t>(bias);
            right=std::clamp(right+static_cast<std::int32_t>(bias),0,1023)-static_cast<std::int32_t>(bias);
            l=left*64; r=right*64;
        }'''


def patch(root):
    root=Path(root)
    header=root/'runtime/include/dsr/spu.h'
    header.write_text(replace(header.read_text(encoding='utf-8'),
        '    void reset();',HEADER+'    void reset();',1),encoding='utf-8')
    source=root/'runtime/spu/src/spu.cpp'
    text=source.read_text(encoding='utf-8')
    changes=(
        ('std::int32_t current=0, predictor=0, initial_predictor=0;',
         'std::int32_t current=0, previous=0, predictor=0, initial_predictor=0;'),
        ('    bool linear=false;',
         '    bool linear=false;\n    Spu::OutputQuality quality=Spu::OutputQuality::Hardware;'),
        ('c.origin=now; c.pos=0; c.current=0; c.duty_pos=0;',
         'c.origin=now; c.pos=0; c.current=0; c.previous=0; c.duty_pos=0;'),
        ('            c.origin+=p;\n            const unsigned fmt=',
         '            c.origin+=p;\n            c.previous=c.current;\n            const unsigned fmt='),
        ('    void capture(unsigned i,std::int32_t value) {',
         AUDIBLE+'    void capture(unsigned i,std::int32_t value) {'),
        ('            const std::int32_t sample=output_channel(n);',
         '            const std::int32_t sample=audible_channel(n);'),
        ('''        left>>=6U; right>>=6U;
        left=std::clamp(left+static_cast<std::int32_t>(bias),0,1023)-static_cast<std::int32_t>(bias);
        right=std::clamp(right+static_cast<std::int32_t>(bias),0,1023)-static_cast<std::int32_t>(bias);
        const int l=left*64, r=right*64;''',OUTPUT),
        ('void Spu::reset() { *impl_=Impl{}; impl_->owner=this; }',
         '''void Spu::reset() {
    const auto quality=impl_->quality;
    *impl_=Impl{}; impl_->owner=this; impl_->quality=quality;
}
void Spu::set_output_quality(OutputQuality quality) { impl_->quality=quality; }'''),
    )
    for before,after in changes:text=replace(text,before,after,1)
    source.write_text(text,encoding='utf-8')
