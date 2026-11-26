"""Coalesce adjacent 32-bit pixels in the pinned GS runtime's write runs."""

from pathlib import Path

from .runtime_patch import replace


def patch(root):
    memory = Path(root) / 'thirdparty/PS2Recomp/ps2xRuntime/src/lib/gs/ps2_gs_memory.cpp'
    implementation = Path(__file__).with_name('gs_write_run_32.inl').read_text(encoding='utf-8').rstrip()
    if '#include <algorithm>\n' not in memory.read_text(encoding='utf-8'):
        replace(memory, '#include <array>\n', '#include <algorithm>\n#include <array>\n')
    replace(memory, 'inline void WriteRun32(', 'inline void WriteRun32Scalar(')
    site = '\n    }\n\n    void WriteRunCT32('
    replace(memory, site, '\n\n' + implementation + site)
