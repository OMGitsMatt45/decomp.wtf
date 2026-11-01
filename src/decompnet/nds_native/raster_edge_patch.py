"""Retain sloped polygon boundary pixels when DS edge coverage is enabled."""
from pathlib import Path
from .capture_patch import replace


def patch(root):
    path = Path(root) / 'runtime/gpu3d/src/gpu3d.cpp'
    text = path.read_text(encoding='utf-8')
    text = replace(text,
        '''        int width = static_cast<int>(right.x) - x;
        if (width <= 0) return;
        std::array<float, 7> value = left.value;
        const float inverse_width = 1.0F / static_cast<float>(width);''',
        '''        int width = static_cast<int>(right.x) - x;
        if (width <= 0) return;
        const int interpolation_width = width;
        // AA and edge marking retain polygon boundary pixels. A sloped right
        // edge must include its endpoint: independently quantized T-junctions
        // can put the adjacent left edge one pixel farther right. Vertical
        // right edges keep their half-open interval. Preserve the original
        // interpolation distance so interior texture/depth samples do not move.
        if ((disp3d & 0x30U) != 0U && (right.x_step != 0 || right.numerator != 0))
            ++width;
        std::array<float, 7> value = left.value;
        const float inverse_width = 1.0F / static_cast<float>(interpolation_width);''')
    path.write_text(text, encoding='utf-8')
