"""Retain projection classification for customized scene/overlay placement."""
from pathlib import Path
from .capture_patch import replace


def patch(root):
    root=Path(root)
    p=root/'runtime/include/dsr/gpu3d.h'
    text=replace(p.read_text(encoding='utf-8'),
        '''    std::uint32_t palette = 0;
    std::uint32_t viewport = 0;
};''',
        '''    std::uint32_t palette = 0;
    std::uint32_t viewport = 0;
    // Observation only. Constant per-vertex W does not prove an orthographic
    // projection (a planar mesh can have constant depth in a perspective view).
    bool perspective = false;
};''')
    p.write_text(text,encoding='utf-8')
    p=root/'runtime/gpu3d/src/gpu3d.cpp'
    text=replace(p.read_text(encoding='utf-8'),
        '        polygon.viewport = get32(0x04000580U);',
        '''        polygon.viewport = get32(0x04000580U);
        polygon.perspective = projection[3] != 0 || projection[7] != 0 || projection[11] != 0;''')
    p.write_text(text,encoding='utf-8')
