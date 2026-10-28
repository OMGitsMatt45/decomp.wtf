"""Optional native foreground observation for customized scene presentation."""
from pathlib import Path
from .capture_patch import replace

CHANGES = (
    ('runtime/gpu2d/src/capture_origin.h', '''// Optional presentation metadata; never changes emulated pixels or registers.
// Included inside Gpu2D::Impl by the pinned runtime integration.
struct CaptureOrigins {
    std::vector<std::uint64_t> vram = std::vector<std::uint64_t>(9U * kBankCapacity / 2U);
    std::array<std::uint64_t, kPixelsPerFrame> a{}, b{}, top{}, bottom{};
    std::array<std::uint64_t, kScreenWidth> composed{};
};
''',
'''// Optional presentation metadata; never changes emulated pixels or registers.
// Included inside Gpu2D::Impl by the pinned runtime integration.
// Foreground values are premultiplied ARGB8 plus bit32 (known), bit33
// (unsupported blend). Transparent known values include a 3D clear pixel.
static constexpr std::uint64_t kForegroundKnown=1ull<<32, kForegroundInvalid=1ull<<33;
struct CaptureOrigins {
    std::vector<std::uint64_t> foreground = std::vector<std::uint64_t>(9U * kBankCapacity / 2U);
    std::array<std::uint64_t,kPixelsPerFrame> fa{},fb{},ftop{},fbottom{};
    std::array<std::uint64_t,kScreenWidth> fcomposed{};
    std::vector<std::uint64_t> vram = std::vector<std::uint64_t>(9U * kBankCapacity / 2U);
    std::array<std::uint64_t, kPixelsPerFrame> a{}, b{}, top{}, bottom{};
    std::array<std::uint64_t, kScreenWidth> composed{};
};
'''),
    ('runtime/gpu2d/src/capture_origin.h', '''std::uint64_t lcdc_origin(unsigned bank, unsigned offset) const {
    if (!origins || bank >= 4 || (vramcnt[bank] & 0x87U) != 0x80U) return 0;
    return origins->vram[bank_offset(bank, offset % kBankSizes[bank]) / 2U];
}
''',
'''std::uint64_t lcdc_origin(unsigned bank, unsigned offset) const {
    if (!origins || bank >= 4 || (vramcnt[bank] & 0x87U) != 0x80U) return 0;
    return origins->vram[bank_offset(bank, offset % kBankSizes[bank]) / 2U];
}

std::uint64_t mapped_foreground(std::uint32_t address) const {
    if (!origins) return 0;
    address = vram_address(address);
    std::uint64_t result = 0; unsigned matches = 0;
    for (std::size_t i=0;i<arm9_map_count;++i) {
        const auto& m=arm9_maps[i];
        if (in_range(address,m.address,m.size)) {
            ++matches;result=origins->foreground[bank_offset(m.bank,m.offset+address-m.address)/2U];
        }
    }
    return matches==1?result:0;
}
std::uint64_t lcdc_foreground(unsigned bank,unsigned offset) const {
    if (!origins||bank>=4||(vramcnt[bank]&0x87U)!=0x80U)return 0;
    return origins->foreground[bank_offset(bank,offset%kBankSizes[bank])/2U];
}
static std::uint64_t native_foreground(Color c) {
    return kForegroundKnown|0xff000000U|(color5_to_8(c.r)<<16)|(color5_to_8(c.g)<<8)|color5_to_8(c.b);
}
static std::uint64_t blend_foreground(std::uint64_t a,std::uint64_t b,unsigned wa,unsigned wb) {
    // A DS blend whose weights sum below 16 also darkens the scene; its
    // missing weight is black opacity in the premultiplied foreground.
    // Additive cases requiring negative opacity retain a native fallback.
    if(wa==16&&wb==0)return a;
    if(wb==16&&wa==0)return b;
    if ((a|b)&kForegroundInvalid || wa+wb>16)return kForegroundKnown|kForegroundInvalid;
    std::uint64_t out=kForegroundKnown;
    for(unsigned shift:{0U,8U,16U})out|=std::uint64_t(std::min(255U,(((unsigned(a>>shift)&255U)*wa+(unsigned(b>>shift)&255U)*wb)/16U)))<<shift;
    const unsigned alpha=(255U*(16U-wa-wb)+(unsigned(a>>24)&255U)*wa+(unsigned(b>>24)&255U)*wb)/16U;
    out|=std::uint64_t(alpha)<<24;
    return out;
}
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''
struct Pixel {
    Color color{};
    std::uint64_t origin = 0; // Optional captured-3D source tag.
    // 3D layer pixels keep the 3D engine's full 6-bit colour for alpha blending.
    std::array<std::uint8_t, 3> rgb6{};
    std::uint8_t priority = 3;
    std::uint8_t layer = 5;
''',
'''
struct Pixel {
    Color color{};
    std::uint64_t origin = 0; // Optional captured-3D source tag.
    std::uint64_t foreground = 0;
    // 3D layer pixels keep the 3D engine's full 6-bit colour for alpha blending.
    std::array<std::uint8_t, 3> rgb6{};
    std::uint8_t priority = 3;
    std::uint8_t layer = 5;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''    }

    void write_bank_byte(std::uint8_t bank, std::uint32_t offset, std::uint8_t value) {
        vram[bank_offset(bank, offset)] = value;
        if (origins) origins->vram[bank_offset(bank, offset) / 2U] = 0;
        vram_generation += static_cast<std::uint64_t>(texture_bank[bank]);
    }

    void write_mapped_byte(VramMap* maps, std::size_t count, std::uint32_t address,
''',
'''    }

    void write_bank_byte(std::uint8_t bank, std::uint32_t offset, std::uint8_t value) {
        vram[bank_offset(bank, offset)] = value;
        if (origins) { origins->vram[bank_offset(bank, offset) / 2U] = 0; origins->foreground[bank_offset(bank, offset) / 2U] = 0; }
        vram_generation += static_cast<std::uint64_t>(texture_bank[bank]);
    }

    void write_mapped_byte(VramMap* maps, std::size_t count, std::uint32_t address,
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                pixel.layer = static_cast<std::uint8_t>(bg);
                pixel.opaque = true;
                pixel.three_d = true;
                if (alpha == 31) pixel.origin = origin_3d(source_x, screen_y);
                line[static_cast<std::size_t>(x)] = pixel;
            }
            return;
        }
''',
'''                pixel.layer = static_cast<std::uint8_t>(bg);
                pixel.opaque = true;
                pixel.three_d = true;
                if (alpha == 31) pixel.origin = origin_3d(source_x, screen_y);
                pixel.foreground = kForegroundKnown;
                line[static_cast<std::size_t>(x)] = pixel;
            }
            return;
        }
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                                     is_a ? 0x7FFFFU : 0x1FFFFU};
        for (int x = 0; x < static_cast<int>(kScreenWidth); ++x) {
            Color color{};
            bool transparent = false;
            std::uint64_t bitmap_origin = 0;
            const bool bitmap = is_extended && (cnt & (1U << 7U)) != 0U;
            const int width = is_large ? large_sizes[size_code][0]
                : bitmap ? bitmap_sizes[size_code][0] : affine_sizes[size_code];
            const int height = is_large ? large_sizes[size_code][1]
''',
'''                                     is_a ? 0x7FFFFU : 0x1FFFFU};
        for (int x = 0; x < static_cast<int>(kScreenWidth); ++x) {
            Color color{};
            bool transparent = false;
            std::uint64_t bitmap_origin = 0, bitmap_foreground = 0;
            const bool bitmap = is_extended && (cnt & (1U << 7U)) != 0U;
            const int width = is_large ? large_sizes[size_code][0]
                : bitmap ? bitmap_sizes[size_code][0] : affine_sizes[size_code];
            const int height = is_large ? large_sizes[size_code][1]
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                const std::uint32_t index = static_cast<std::uint32_t>(source_y * width + source_x);
                if (direct) {
                    const std::uint16_t raw = bg_vram.half(bitmap_base + index * 2U);
                    bitmap_origin = mapped_origin(bg_vram.base + ((bitmap_base + index * 2U) & bg_vram.mask));
                    transparent = (raw & 0x8000U) == 0U;
                    if (!transparent) {
                        color = direct_color(raw);
                    }
''',
'''                const std::uint32_t index = static_cast<std::uint32_t>(source_y * width + source_x);
                if (direct) {
                    const std::uint16_t raw = bg_vram.half(bitmap_base + index * 2U);
                    bitmap_origin = mapped_origin(bg_vram.base + ((bitmap_base + index * 2U) & bg_vram.mask));
                    bitmap_foreground = mapped_foreground(bg_vram.base + ((bitmap_base + index * 2U) & bg_vram.mask));
                    transparent = (raw & 0x8000U) == 0U;
                    if (!transparent) {
                        color = direct_color(raw);
                    }
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''            }
            Pixel pixel;
            pixel.color = color;
            pixel.origin = bitmap_origin;
            pixel.priority = static_cast<std::uint8_t>(cnt & 3U);
            pixel.layer = static_cast<std::uint8_t>(bg);
            pixel.opaque = true;
            line[static_cast<std::size_t>(x)] = pixel;
''',
'''            }
            Pixel pixel;
            pixel.color = color;
            pixel.origin = bitmap_origin;
            pixel.foreground = bitmap_foreground;
            pixel.priority = static_cast<std::uint8_t>(cnt & 3U);
            pixel.layer = static_cast<std::uint8_t>(bg);
            pixel.opaque = true;
            line[static_cast<std::size_t>(x)] = pixel;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''        const bool engine_enabled = (powcnt1 & (1U << (is_a ? 1U : 9U))) != 0U;
        const std::uint32_t display_mode = (dispcnt >> 16U) & 3U;
        const bool needs_capture = is_a && capture_active;
        auto* origin_line = origins ? (is_a ? origins->a.data() : origins->b.data()) + y * kScreenWidth : nullptr;
        if (origin_line) { std::fill_n(origin_line, kScreenWidth, 0); if (is_a) origins->composed.fill(0); }
        auto* mask_line = is_a ? three_d_mask_buffer.data() + y * kScreenWidth
                              : unused_mask_line.data();
        const bool normal_display = engine_enabled && (dispcnt & (1U << 7U)) == 0U &&
                                    display_mode == 1U;
''',
'''        const bool engine_enabled = (powcnt1 & (1U << (is_a ? 1U : 9U))) != 0U;
        const std::uint32_t display_mode = (dispcnt >> 16U) & 3U;
        const bool needs_capture = is_a && capture_active;
        auto* origin_line = origins ? (is_a ? origins->a.data() : origins->b.data()) + y * kScreenWidth : nullptr;
        if (origin_line) { std::fill_n(origin_line, kScreenWidth, 0); if (is_a) {origins->composed.fill(0);origins->fcomposed.fill(kForegroundKnown);} }
        auto* foreground_line=origins?(is_a?origins->fa.data():origins->fb.data())+y*kScreenWidth:nullptr;
        if(foreground_line)std::fill_n(foreground_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);
        auto* mask_line = is_a ? three_d_mask_buffer.data() + y * kScreenWidth
                              : unused_mask_line.data();
        const bool normal_display = engine_enabled && (dispcnt & (1U << 7U)) == 0U &&
                                    display_mode == 1U;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''        if (!needs_capture && is_a && display_mode >= 2U) {
            const auto bank = static_cast<std::uint8_t>((dispcnt >> 18U) & 3U);
            if (display_mode == 2U) {
                fill_lcdc_line(output, bank, y);
                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U);
            } else {
                for (std::size_t x = 0; x < kScreenWidth; ++x) {
                    output[x] = direct_color(next_fifo_pixel());
                }
''',
'''        if (!needs_capture && is_a && display_mode >= 2U) {
            const auto bank = static_cast<std::uint8_t>((dispcnt >> 18U) & 3U);
            if (display_mode == 2U) {
                fill_lcdc_line(output, bank, y);
                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) { origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U); const auto fg=lcdc_foreground(bank,y*512U+x*2U);foreground_line[x]=fg?fg:native_foreground(output[x]); }
            } else {
                for (std::size_t x = 0; x < kScreenWidth; ++x) {
                    output[x] = direct_color(next_fifo_pixel());
                }
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''            const bool effects_allowed = (mask & (1U << 5U)) != 0U;
            Color dst = backdrop;
            std::uint8_t dst_layer = kBackdropLayer;
            bool dst_three_d = false;
            std::uint64_t dst_origin = 0;
            // Layers are painted from the lowest priority up; each pixel is composited over
            // whatever the painted layers below left in `dst`.
            const auto composite = [&](const Pixel& source, std::uint8_t layer) {
                const std::uint32_t layer_bit = 1U << layer;
''',
'''            const bool effects_allowed = (mask & (1U << 5U)) != 0U;
            Color dst = backdrop;
            std::uint8_t dst_layer = kBackdropLayer;
            bool dst_three_d = false;
            std::uint64_t dst_origin = 0, dst_foreground=kForegroundKnown;
            // Layers are painted from the lowest priority up; each pixel is composited over
            // whatever the painted layers below left in `dst`.
            const auto composite = [&](const Pixel& source, std::uint8_t layer) {
                const std::uint32_t layer_bit = 1U << layer;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                    dst = darken(source.color, evy);
                } else {
                    dst = source.color;
                }
                dst_layer = layer;
                // An opaque 3D fragment over a second target still goes through
                // blend_3d, but alpha31 makes it an exact colour identity.
                const bool identity_blend = (source.three_d && source.color.alpha == 31U) ||
''',
'''                    dst = darken(source.color, evy);
                } else {
                    dst = source.color;
                }
                if(origins) {
                    const auto foreground=source.foreground?source.foreground:native_foreground(source.color);
                    if(source.three_d) {
                        if(source.color.alpha==31||!(dst_foreground&0xffffffffU))dst_foreground=kForegroundKnown;
                        else dst_foreground=kForegroundKnown|kForegroundInvalid;
                    } else if(blends) {
                        const auto a=source.semi&&source.color.alpha!=31U?unsigned(source.color.alpha):std::min(eva,16U);
                        const auto b=source.semi&&source.color.alpha!=31U?16U-a:std::min(evb,16U);
                        dst_foreground=blend_foreground(foreground,dst_foreground,a,b);
                    } else if(brightness&&evy)dst_foreground=kForegroundKnown|kForegroundInvalid;
                    else dst_foreground=foreground;
                }
                dst_layer = layer;
                // An opaque 3D fragment over a second target still goes through
                // blend_3d, but alpha31 makes it an exact colour identity.
                const bool identity_blend = (source.three_d && source.color.alpha == 31U) ||
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                    composite(pixel, layer);
                }
            }
            output[xi] = dst;
            if (origin_line) { origin_line[xi] = normal_display && !master_changes_color ? dst_origin : 0; if (is_a) origins->composed[xi] = dst_origin; }
            mask_line[xi] = static_cast<std::uint8_t>(dst_three_d && raw_three_d_display);
        }
        if (is_a) {
            capture_display_line = output;
''',
'''                    composite(pixel, layer);
                }
            }
            output[xi] = dst;
            if (origin_line) {
                origin_line[xi] = normal_display && !master_changes_color ? dst_origin : 0;
                foreground_line[xi]=normal_display&&!master_changes_color?dst_foreground:kForegroundKnown|kForegroundInvalid;
                if(is_a){origins->composed[xi]=dst_origin;origins->fcomposed[xi]=dst_foreground;}
            }
            mask_line[xi] = static_cast<std::uint8_t>(dst_three_d && raw_three_d_display);
        }
        if (is_a) {
            capture_display_line = output;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''        } else if (is_a && display_mode >= 2U) {
            const auto bank = static_cast<std::uint8_t>((dispcnt >> 18U) & 3U);
            if (display_mode == 2U) {
                fill_lcdc_line(output, bank, y);
                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U);
            } else {
                for (std::size_t x = 0; x < kScreenWidth; ++x) {
                    output[x] = direct_color(next_fifo_pixel());
                }
''',
'''        } else if (is_a && display_mode >= 2U) {
            const auto bank = static_cast<std::uint8_t>((dispcnt >> 18U) & 3U);
            if (display_mode == 2U) {
                fill_lcdc_line(output, bank, y);
                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) { origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U); const auto fg=lcdc_foreground(bank,y*512U+x*2U);foreground_line[x]=fg?fg:native_foreground(output[x]); }
            } else {
                for (std::size_t x = 0; x < kScreenWidth; ++x) {
                    output[x] = direct_color(next_fifo_pixel());
                }
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''            // opaque, a 3D pixel is opaque when its alpha is non-zero (partial alpha is
            // not weighed into the capture).
            Color source_a = capture_display_line[x];
            std::uint64_t a_origin = origins ? origins->composed[x] : 0, b_origin = 0;
            bool a_opaque = true;
            if (source_a_3d) {
                const std::uint32_t raw = line3d != nullptr ? line3d[x] : 0U;
                source_a = {static_cast<std::uint8_t>((raw & 63U) >> 1U),
                            static_cast<std::uint8_t>(((raw >> 6U) & 63U) >> 1U),
                            static_cast<std::uint8_t>(((raw >> 12U) & 63U) >> 1U), 31U};
                a_opaque = ((raw >> 24U) & 31U) != 0U;
                a_origin = ((raw >> 24U) & 31U) == 31U ? origin_3d(x, y) : 0;
            }
            Color source_b{};
            bool b_opaque = true;
            if (source_b_fifo) {
''',
'''            // opaque, a 3D pixel is opaque when its alpha is non-zero (partial alpha is
            // not weighed into the capture).
            Color source_a = capture_display_line[x];
            std::uint64_t a_origin = origins ? origins->composed[x] : 0, b_origin = 0;
            std::uint64_t a_foreground=origins?origins->fcomposed[x]:0,b_foreground=0;
            bool a_opaque = true;
            if (source_a_3d) {
                const std::uint32_t raw = line3d != nullptr ? line3d[x] : 0U;
                source_a = {static_cast<std::uint8_t>((raw & 63U) >> 1U),
                            static_cast<std::uint8_t>(((raw >> 6U) & 63U) >> 1U),
                            static_cast<std::uint8_t>(((raw >> 12U) & 63U) >> 1U), 31U};
                a_opaque = ((raw >> 24U) & 31U) != 0U;
                a_origin = ((raw >> 24U) & 31U) == 31U ? origin_3d(x, y) : 0;
                a_foreground=kForegroundKnown;
            }
            Color source_b{};
            bool b_opaque = true;
            if (source_b_fifo) {
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                const std::uint32_t source_offset = ((vram_display ? 0U : read_offset) * 0x8000U +
                    static_cast<std::uint32_t>(y) * 512U + x * 2U) % 0x20000U;
                const std::uint16_t raw = read_lcdc_half(static_cast<std::uint8_t>(read_bank), source_offset);
                b_origin = lcdc_origin(read_bank, source_offset);
                source_b = direct_color(raw);
                b_opaque = (raw & 0x8000U) != 0U;
            }
            Color captured = source_a;
            bool alpha = a_opaque;
            if (source_mode == 1U) {
                captured = source_b;
''',
'''                const std::uint32_t source_offset = ((vram_display ? 0U : read_offset) * 0x8000U +
                    static_cast<std::uint32_t>(y) * 512U + x * 2U) % 0x20000U;
                const std::uint16_t raw = read_lcdc_half(static_cast<std::uint8_t>(read_bank), source_offset);
                b_origin = lcdc_origin(read_bank, source_offset);
                b_foreground=lcdc_foreground(read_bank,source_offset);
                source_b = direct_color(raw);
                b_opaque = (raw & 0x8000U) != 0U;
            }
            if(origins&&!b_foreground)b_foreground=native_foreground(source_b);
            Color captured = source_a;
            bool alpha = a_opaque;
            if (source_mode == 1U) {
                captured = source_b;
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''                    const unsigned wa = a_opaque ? std::min(eva, 16U) : 0, wb = b_opaque ? std::min(evb, 16U) : 0;
                    if (wa == 16 && wb == 0) tag = a_origin;
                    if (wb == 16 && wa == 0) tag = b_origin;
                }
                origins->vram[bank_offset(dst_bank, target % kBankSizes[dst_bank]) / 2U] = tag;
            }
        }
    }

''',
'''                    const unsigned wa = a_opaque ? std::min(eva, 16U) : 0, wb = b_opaque ? std::min(evb, 16U) : 0;
                    if (wa == 16 && wb == 0) tag = a_origin;
                    if (wb == 16 && wa == 0) tag = b_origin;
                }
                const auto index=bank_offset(dst_bank,target%kBankSizes[dst_bank])/2U;
                origins->vram[index] = tag;
                origins->foreground[index]=source_mode==0?a_foreground:source_mode==1?b_foreground:
                    blend_foreground(a_foreground,b_foreground,a_opaque?std::min(eva,16U):0U,b_opaque?std::min(evb,16U):0U);
            }
        }
    }

'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''            const auto* a = origins->a.data() + row;
            const auto* b = origins->b.data() + row;
            std::copy_n(a_on_top ? a : b, kScreenWidth, origins->top.data() + row);
            std::copy_n(a_on_top ? b : a, kScreenWidth, origins->bottom.data() + row);
        }
        capture_line(y);
    }

''',
'''            const auto* a = origins->a.data() + row;
            const auto* b = origins->b.data() + row;
            std::copy_n(a_on_top ? a : b, kScreenWidth, origins->top.data() + row);
            std::copy_n(a_on_top ? b : a, kScreenWidth, origins->bottom.data() + row);
            const auto* fa=origins->fa.data()+row;const auto* fb=origins->fb.data()+row;
            std::copy_n(a_on_top?fa:fb,kScreenWidth,origins->ftop.data()+row);
            std::copy_n(a_on_top?fb:fa,kScreenWidth,origins->fbottom.data()+row);
        }
        capture_line(y);
    }

'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''        rebuild_mappings();
        mapping_generation = 0;
        vram_generation = 0;
        three_d_mask_buffer.fill(0);
        if (origins) { std::fill(origins->vram.begin(), origins->vram.end(), 0); origins->a.fill(0); origins->b.fill(0); origins->top.fill(0); origins->bottom.fill(0); origins->composed.fill(0); }
    }
};

void gpu2d_detail::Gpu2DTestAccess::write_bank_byte(
''',
'''        rebuild_mappings();
        mapping_generation = 0;
        vram_generation = 0;
        three_d_mask_buffer.fill(0);
        if (origins) { std::fill(origins->vram.begin(), origins->vram.end(), 0); origins->a.fill(0); origins->b.fill(0); origins->top.fill(0); origins->bottom.fill(0); origins->composed.fill(0);
            std::fill(origins->foreground.begin(),origins->foreground.end(),0);origins->fa.fill(0);origins->fb.fill(0);origins->ftop.fill(0);origins->fbottom.fill(0);origins->fcomposed.fill(0); }
    }
};

void gpu2d_detail::Gpu2DTestAccess::write_bank_byte(
'''),
    ('runtime/gpu2d/src/gpu2d.cpp', '''    visit(impl_->origins->top); visit(impl_->origins->bottom);
    return generations;
}
}
''',
'''    visit(impl_->origins->top); visit(impl_->origins->bottom);
    return generations;
}
}

namespace dsr {
const std::uint64_t* Gpu2D::screen_top_foreground() const {return impl_->origins?impl_->origins->ftop.data():nullptr;}
const std::uint64_t* Gpu2D::screen_bottom_foreground() const {return impl_->origins?impl_->origins->fbottom.data():nullptr;}
}
'''),
    ('runtime/include/dsr/gpu2d.h', '''    void set_capture_origin_tracking(bool enabled);
    const std::uint64_t* screen_top_origins() const;
    const std::uint64_t* screen_bottom_origins() const;
    std::vector<std::uint64_t> capture_origin_generations() const;
    // The display's 5-bit -> 8-bit channel expansion, for host code that composes pixels
    // outside the 2D compositor (for example the optional hi-res 3D overlay).
    static std::uint8_t expand_color5(std::uint32_t value);

''',
'''    void set_capture_origin_tracking(bool enabled);
    const std::uint64_t* screen_top_origins() const;
    const std::uint64_t* screen_bottom_origins() const;
    std::vector<std::uint64_t> capture_origin_generations() const;
    // Optional native 2D foreground, premultiplied ARGB8, known bit32 and
    // unsupported-composition bit33. Never alters the native LCD output.
    const std::uint64_t* screen_top_foreground() const;
    const std::uint64_t* screen_bottom_foreground() const;
    // The display's 5-bit -> 8-bit channel expansion, for host code that composes pixels
    // outside the 2D compositor (for example the optional hi-res 3D overlay).
    static std::uint8_t expand_color5(std::uint32_t value);

'''),
)


def patch(root):
    root = Path(root)
    for name, before, after in CHANGES:
        path = root/name
        path.write_text(replace(path.read_text(encoding="utf-8"), before, after), encoding="utf-8")
