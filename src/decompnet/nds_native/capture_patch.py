'''Preserve optional captured-3D origins without changing DS rendering.'''
from pathlib import Path
import shutil

GPU2D_CHANGES = (
    ('''#include <algorithm>''',
'''#include <algorithm>
#include <memory>
#include <vector>''', 1),
    ('''    Gpu3D* gpu3d = nullptr;''',
'''    Gpu3D* gpu3d = nullptr;
#include "capture_origin.h"''', 1),
    ('''        vram[bank_offset(bank, offset)] = value;''',
'''        vram[bank_offset(bank, offset)] = value;
        if (origins) origins->vram[bank_offset(bank, offset) / 2U] = 0;''', 1),
    ('''                    const std::uint16_t raw = bg_vram.half(bitmap_base + index * 2U);''',
'''                    const std::uint16_t raw = bg_vram.half(bitmap_base + index * 2U);
                    bitmap_origin = mapped_origin(bg_vram.base + ((bitmap_base + index * 2U) & bg_vram.mask));''', 1),
    ('''            pixel.color = color;
            pixel.priority = static_cast<std::uint8_t>(cnt & 3U);
            pixel.layer = static_cast<std::uint8_t>(bg);''',
'''            pixel.color = color;
            pixel.origin = bitmap_origin;
            pixel.priority = static_cast<std::uint8_t>(cnt & 3U);
            pixel.layer = static_cast<std::uint8_t>(bg);''', 1),
    ('''        const bool needs_capture = is_a && capture_active;''',
'''        const bool needs_capture = is_a && capture_active;
        auto* origin_line = origins ? (is_a ? origins->a.data() : origins->b.data()) + y * kScreenWidth : nullptr;
        if (origin_line) { std::fill_n(origin_line, kScreenWidth, 0); if (is_a) origins->composed.fill(0); }''', 1),
    ('''        const bool copy_only = target2 == 0U && (effect == 0U || target1 == 0U);''',
'''        const bool copy_only = !origins && target2 == 0U && (effect == 0U || target1 == 0U);''', 1),
    ('''            bool dst_three_d = false;''',
'''            bool dst_three_d = false;
            std::uint64_t dst_origin = 0;''', 1),
    ('''                dst_layer = layer;''',
'''                dst_layer = layer;
                // An opaque 3D fragment over a second target still goes through
                // blend_3d, but alpha31 makes it an exact colour identity.
                const bool identity_blend = (source.three_d && source.color.alpha == 31U) ||
                    (!source.three_d && (!source.semi || source.color.alpha == 31U) && eva >= 16U && evb == 0U);
                dst_origin = (!blends || identity_blend) && (brightness == 0U || evy == 0U) ? source.origin : 0;''', 1),
    ('''            output[xi] = dst;''',
'''            output[xi] = dst;
            if (origin_line) { origin_line[xi] = normal_display && !master_changes_color ? dst_origin : 0; if (is_a) origins->composed[xi] = dst_origin; }''', 1),
    ('''            Color source_a = capture_display_line[x];''',
'''            Color source_a = capture_display_line[x];
            std::uint64_t a_origin = origins ? origins->composed[x] : 0, b_origin = 0;''', 1),
    ('''                a_opaque = ((raw >> 24U) & 31U) != 0U;''',
'''                a_opaque = ((raw >> 24U) & 31U) != 0U;
                a_origin = ((raw >> 24U) & 31U) == 31U ? origin_3d(x, y) : 0;''', 1),
    ('''                const std::uint16_t raw = read_lcdc_half(static_cast<std::uint8_t>(read_bank), source_offset);''',
'''                const std::uint16_t raw = read_lcdc_half(static_cast<std::uint8_t>(read_bank), source_offset);
                b_origin = lcdc_origin(read_bank, source_offset);''', 1),
    ('''            write_lcdc_half(dst_bank, target, raw);''',
'''            write_lcdc_half(dst_bank, target, raw);
            if (origins) {
                std::uint64_t tag = source_mode == 0 ? a_origin : source_mode == 1 ? b_origin : 0;
                if (source_mode >= 2) {
                    const unsigned wa = a_opaque ? std::min(eva, 16U) : 0, wb = b_opaque ? std::min(evb, 16U) : 0;
                    if (wa == 16 && wb == 0) tag = a_origin;
                    if (wb == 16 && wa == 0) tag = b_origin;
                }
                origins->vram[bank_offset(dst_bank, target % kBankSizes[dst_bank]) / 2U] = tag;
            }''', 1),
    ('''    return impl_->arm9_pages[(addr - kVramBase) / kPageSize];''',
'''    return impl_->origins ? nullptr : impl_->arm9_pages[(addr - kVramBase) / kPageSize];''', 1),
    ('''    return impl_->arm7_pages[(addr - kVramBase) / kPageSize];''',
'''    return impl_->origins ? nullptr : impl_->arm7_pages[(addr - kVramBase) / kPageSize];''', 1),
    ('''        three_d_mask_buffer.fill(0);''',
'''        three_d_mask_buffer.fill(0);
        if (origins) { std::fill(origins->vram.begin(), origins->vram.end(), 0); origins->a.fill(0); origins->b.fill(0); origins->top.fill(0); origins->bottom.fill(0); origins->composed.fill(0); }''', 1),
    ('''struct Pixel {
    Color color{};''',
'''struct Pixel {
    Color color{};
    std::uint64_t origin = 0; // Optional captured-3D source tag.''', 1),
    ('''            Color color{};
            bool transparent = false;
            const bool bitmap''',
'''            Color color{};
            bool transparent = false;
            std::uint64_t bitmap_origin = 0;
            const bool bitmap''', 1),
    ('''                pixel.three_d = true;''',
'''                pixel.three_d = true;
                if (alpha == 31) pixel.origin = origin_3d(source_x, screen_y);''', 1),
    ('''        capture_line(y);''',
'''        if (origins) {
            const auto* a = origins->a.data() + row;
            const auto* b = origins->b.data() + row;
            std::copy_n(a_on_top ? a : b, kScreenWidth, origins->top.data() + row);
            std::copy_n(a_on_top ? b : a, kScreenWidth, origins->bottom.data() + row);
        }
        capture_line(y);''', 1),
    ('''
                fill_lcdc_line(output, bank, y);''',
'''
                fill_lcdc_line(output, bank, y);
                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U);''', 2),
)

GPU3D_CHANGES = (
    ('''    std::uint64_t render_generation = 0;''',
'''    std::uint64_t render_generation = 0;
    std::uint64_t raster_serial = 0;''', 1),
    ('''    if (on_render_complete) on_render_complete();''',
'''    ++impl_->raster_serial;
    if (on_render_complete) on_render_complete();''', 1),
    ('''const std::uint32_t* Gpu3D::line(int y) const {''',
'''std::uint64_t Gpu3D::render_serial() const { return impl_->raster_serial; }

const std::uint32_t* Gpu3D::line(int y) const {''', 1),
)

GPU2D_API = '''
    // Optional, observational presentation metadata. Each tag is
    // (3D generation << 16) | (source_y * 256 + source_x + 1); zero is invalid.
    // Borrowed until the next step/mutation. CPU writes invalidate origins.
    void set_capture_origin_tracking(bool enabled);
    const std::uint64_t* screen_top_origins() const;
    const std::uint64_t* screen_bottom_origins() const;
    std::vector<std::uint64_t> capture_origin_generations() const;'''

GPU2D_METHODS = '''
namespace dsr {
void Gpu2D::set_capture_origin_tracking(bool enabled) {
    if (bool(impl_->origins) == enabled) return;
    impl_->origins = enabled ? std::make_unique<Impl::CaptureOrigins>() : nullptr;
    if (on_vram_remap) on_vram_remap(); // All CPU/DMA writes must invalidate tags.
}
const std::uint64_t* Gpu2D::screen_top_origins() const {
    return impl_->origins ? impl_->origins->top.data() : nullptr;
}
const std::uint64_t* Gpu2D::screen_bottom_origins() const {
    return impl_->origins ? impl_->origins->bottom.data() : nullptr;
}
}

namespace dsr {
std::vector<std::uint64_t> Gpu2D::capture_origin_generations() const {
    std::vector<std::uint64_t> generations;
    if (!impl_->origins) return generations;
    std::uint64_t last = ~std::uint64_t(0);
    const auto visit = [&](const auto& tags) {
        for (auto tag : tags) if (tag) {
            const auto generation = tag >> 16;
            if (generation != last) {
                last = generation;
                if (std::find(generations.begin(), generations.end(), generation) == generations.end())
                    generations.push_back(generation);
            }
        }
    };
    visit(impl_->origins->vram);
    visit(impl_->origins->top); visit(impl_->origins->bottom);
    return generations;
}
}
'''


def replace(text, before, after, count=1):
    if text.count(before) != count:
        raise ValueError('pinned DS capture integration site differs: '+before[:80])
    return text.replace(before, after)


def patch(root):
    root = Path(root)
    source = root/'runtime/gpu2d/src/gpu2d.cpp'
    text = source.read_text(encoding='utf-8')
    for before, after, count in GPU2D_CHANGES:
        text = replace(text, before, after, count)
    source.write_text(text+GPU2D_METHODS, encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('capture_origin.h'), source.with_name('capture_origin.h'))
    header = root/'runtime/include/dsr/gpu2d.h'
    text = header.read_text(encoding='utf-8')
    text = replace(text, '    const std::uint8_t* three_d_mask() const;',
                   '    const std::uint8_t* three_d_mask() const;'+GPU2D_API)
    text = replace(text, '#include <functional>', '#include <functional>\n#include <vector>')
    header.write_text(text, encoding='utf-8')
    header = root/'runtime/include/dsr/gpu3d.h'
    text = header.read_text(encoding='utf-8')
    text = replace(text, '    void render_start();',
                   '    void render_start();\n    // Unique completed raster, including texture-only changes and reset.\n    std::uint64_t render_serial() const;')
    header.write_text(text, encoding='utf-8')
    source = root/'runtime/gpu3d/src/gpu3d.cpp'
    text = source.read_text(encoding='utf-8')
    for before, after, count in GPU3D_CHANGES:
        text = replace(text, before, after, count)
    source.write_text(text, encoding='utf-8')
    # The upstream GPU2D unit suite uses a fake GPU3D rather than its library.
    test = root/'runtime/gpu2d/tests/gpu2d_tests.cpp'
    text = test.read_text(encoding='utf-8')
    text = replace(text, 'Gpu3D::~Gpu3D() = default;',
                   'Gpu3D::~Gpu3D() = default;\nstd::uint64_t Gpu3D::render_serial() const { return 1; }')
    test.write_text(text, encoding='utf-8')
