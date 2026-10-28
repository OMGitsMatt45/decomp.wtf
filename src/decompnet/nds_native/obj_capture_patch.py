"""Keep captured-scene provenance when VRAM is displayed through bitmap OBJ."""
from pathlib import Path
from .capture_patch import replace

CHANGES = (
    ('''                    Color color{};
                    bool transparent = false;
                    bool semitransparent = mode == 1;''',
     '''                    Color color{};
                    std::uint64_t bitmap_origin = 0, bitmap_foreground = 0;
                    bool transparent = false;
                    bool semitransparent = mode == 1;'''),
    ('''                        const std::uint16_t raw = read_obj_half(address, is_a);
                        transparent = (raw & 0x8000U) == 0U;''',
     '''                        const std::uint16_t raw = read_obj_half(address, is_a);
                        if (origins) {
                            // Match read_obj_half's engine-specific address wrap.
                            const auto base = is_a ? 0x06400000U : 0x06600000U;
                            constexpr auto mask = 0x3ffffU;
                            bitmap_origin = mapped_origin(base + (address & mask));
                            bitmap_foreground = mapped_foreground(base + (address & mask));
                        }
                        transparent = (raw & 0x8000U) == 0U;'''),
    ('''                        existing.color = color;
                        existing.priority = priority;''',
     '''                        existing.color = color;
                        existing.origin = bitmap_origin;
                        existing.foreground = bitmap_foreground;
                        existing.priority = priority;'''),
    ('''                pixel.color = cached.color;
                pixel.opaque = cached.opaque;''',
     '''                pixel.color = cached.color;
                pixel.origin = cached.origin;
                pixel.foreground = cached.foreground;
                pixel.opaque = cached.opaque;'''),
    ('''                const bool identity_blend = (source.three_d && source.color.alpha == 31U) ||
                    (!source.three_d && (!source.semi || source.color.alpha == 31U) && eva >= 16U && evb == 0U);''',
     '''                const bool identity_blend = (source.three_d && source.color.alpha == 31U) ||
                    (!source.three_d && source.semi && source.color.alpha == 16U) ||
                    (!source.three_d && (!source.semi || source.color.alpha == 31U) && eva >= 16U && evb == 0U);'''),
)


def patch(root):
    path = Path(root)/'runtime/gpu2d/src/gpu2d.cpp'
    text = path.read_text(encoding='utf-8')
    for before, after in CHANGES:
        text = replace(text, before, after)
    path.write_text(text, encoding='utf-8')
