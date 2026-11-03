"""Use SSE2 for flag-free vector arithmetic without changing guest timing."""
from pathlib import Path
from .runtime_patch import replace

def patch(root):
    folder=Path(root)/'thirdparty/PS2Recomp/ps2xRuntime/src/lib/vu'
    header=folder/'ps2_vu1_program.h'
    replace(header,'#if PS2_VU_PROGRAM_NEON\n// The upper instructions',
        '#if PS2_VU_PROGRAM_SSE\n#include "decomp_vu_plain_sse.hpp"\n#endif\n\n#if PS2_VU_PROGRAM_NEON\n// The upper instructions')
    replace(header,'#else\n// The same instructions lane by lane, in computeUpper\'s arithmetic.',
        '''#elif PS2_VU_PROGRAM_SSE
template<uint32_t Upper>
PS2_VU_FORCE_INLINE uint32_t Frame::plainUpper(float *value) {
    return sse_plain::run<Upper>(m_state,value);
}
#else
// The same instructions lane by lane, in computeUpper's arithmetic.''')
    (folder/'decomp_vu_plain_sse.hpp').write_bytes(Path(__file__).with_name('vu_plain_sse.hpp').read_bytes())
