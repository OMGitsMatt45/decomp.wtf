"""Expose pre-master scene composition and exact per-line LCD brightness state."""
from pathlib import Path
from .capture_patch import replace

CHANGES = (
 ('runtime/gpu2d/src/capture_origin.h',
  '    std::array<std::uint64_t,kScreenWidth> fcomposed{};',
  '''    std::array<std::uint64_t,kScreenWidth> fcomposed{};
    // Separate from the legacy final-foreground plane: master brightness is
    // applied after the complete scene and its native UI have been presented.
    std::array<std::uint64_t,kScreenWidth> scene_a{},scene_b{};
    std::array<std::uint64_t,kPixelsPerFrame> scene_top{},scene_bottom{};
    std::array<std::uint8_t,kScreenHeight> brightness_top{},brightness_bottom{};
    std::uint8_t brightness_a=0,brightness_b=0;''',1),
 ('runtime/gpu2d/src/capture_origin.h',
  'static std::uint64_t blend_foreground(',
  '''static std::uint64_t brightness_foreground(std::uint64_t foreground,unsigned mode,unsigned factor) {
    if(foreground&kForegroundInvalid)return foreground;
    if(!factor||(mode!=2&&mode!=3))return foreground;
    const auto alpha=unsigned(foreground>>24)&255U;
    std::uint64_t result=kForegroundKnown|std::uint64_t(alpha+(255U-alpha)*factor/16U)<<24;
    for(unsigned shift:{0U,8U,16U}) {
        const auto value=unsigned(foreground>>shift)&255U;
        const auto changed=mode==2?value+(255U-value)*factor/16U:value-value*factor/16U;
        result|=std::uint64_t(changed)<<shift;
    }
    return result;
}
static std::uint64_t blend_foreground(''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '        if(foreground_line)std::fill_n(foreground_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);',
  '''        if(foreground_line)std::fill_n(foreground_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);
        auto* scene_line=origins?(is_a?origins->scene_a.data():origins->scene_b.data()):nullptr;
        if(scene_line)std::fill_n(scene_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''        const bool master_changes_color = (master_mode == 1U || master_mode == 2U) &&
                                          (master & 31U) != 0U;''',
  '''        const bool master_changes_color = (master_mode == 1U || master_mode == 2U) &&
                                          (master & 31U) != 0U;
        if(origins)(is_a?origins->brightness_a:origins->brightness_b)=master_changes_color?
            std::uint8_t((master_mode<<5U)|std::min(16U,unsigned(master&31U))):0;''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''            output.fill({31U, 31U, 31U, 31U});
            return output[0];''',
  '''            output.fill({31U, 31U, 31U, 31U});
            if(scene_line){std::fill_n(scene_line,kScreenWidth,kForegroundKnown);(is_a?origins->brightness_a:origins->brightness_b)=48;}
            return output[0];''',2),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''                    } else if(brightness&&evy)dst_foreground=kForegroundKnown|kForegroundInvalid;
                    else dst_foreground=foreground;''',
  '''                    } else dst_foreground=foreground;
                    if(!blends&&brightness&&evy)dst_foreground=brightness_foreground(dst_foreground,brightness,evy);''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''                foreground_line[xi]=normal_display&&!master_changes_color?dst_foreground:kForegroundKnown|kForegroundInvalid;''',
  '''                foreground_line[xi]=normal_display&&!master_changes_color?dst_foreground:kForegroundKnown|kForegroundInvalid;
                scene_line[xi]=normal_display?dst_foreground:kForegroundKnown|kForegroundInvalid;''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) { origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U); const auto fg=lcdc_foreground(bank,y*512U+x*2U);foreground_line[x]=fg?fg:native_foreground(output[x]); }''',
  '''                if (origin_line && !master_changes_color) for (unsigned x = 0; x < kScreenWidth; ++x) { origin_line[x] = lcdc_origin(bank, y * 512U + x * 2U); const auto fg=lcdc_foreground(bank,y*512U+x*2U);foreground_line[x]=fg?fg:native_foreground(output[x]); }
                if(scene_line)for(unsigned x=0;x<kScreenWidth;++x){const auto fg=lcdc_foreground(bank,y*512U+x*2U);scene_line[x]=fg?fg:native_foreground(output[x]);}''',2),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''            output.fill({31U, 31U, 31U, 31U});
        } else if (is_a && display_mode >= 2U) {''',
  '''            output.fill({31U, 31U, 31U, 31U});
            if(scene_line){std::fill_n(scene_line,kScreenWidth,kForegroundKnown);(is_a?origins->brightness_a:origins->brightness_b)=48;}
        } else if (is_a && display_mode >= 2U) {''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '''            std::copy_n(a_on_top?fb:fa,kScreenWidth,origins->fbottom.data()+row);''',
  '''            std::copy_n(a_on_top?fb:fa,kScreenWidth,origins->fbottom.data()+row);
            std::copy_n(a_on_top?origins->scene_a.data():origins->scene_b.data(),kScreenWidth,origins->scene_top.data()+row);
            std::copy_n(a_on_top?origins->scene_b.data():origins->scene_a.data(),kScreenWidth,origins->scene_bottom.data()+row);
            origins->brightness_top[y]=a_on_top?origins->brightness_a:origins->brightness_b;
            origins->brightness_bottom[y]=a_on_top?origins->brightness_b:origins->brightness_a;''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  'origins->fbottom.fill(0);origins->fcomposed.fill(0); }',
  '''origins->fbottom.fill(0);origins->fcomposed.fill(0);
            origins->scene_a.fill(0);origins->scene_b.fill(0);origins->scene_top.fill(0);origins->scene_bottom.fill(0);
            origins->brightness_top.fill(0);origins->brightness_bottom.fill(0);origins->brightness_a=origins->brightness_b=0; }''',1),
 ('runtime/include/dsr/gpu2d.h',
  '    const std::uint64_t* screen_bottom_foreground() const;',
  '''    const std::uint64_t* screen_bottom_foreground() const;
    // Premultiplied ARGB8 foreground before LCD master brightness. Same known/
    // invalid bits as foreground(); optional, borrowed until the next render.
    const std::uint64_t* screen_top_scene_foreground() const;
    const std::uint64_t* screen_bottom_scene_foreground() const;
    // 192 rows, routed through LCD swaps at scanline time. Bits5..6: 0 none,
    // 1 brighten, 2 darken; low5: factor clamped to0..16. Forced blank: brighten16.
    const std::uint8_t* screen_top_brightness() const;
    const std::uint8_t* screen_bottom_brightness() const;''',1),
)

# Preserve the raster identity before master brightness, separately from the
# legacy final-colour eligibility plane. Enhanced presentation applies the
# exact LCD brightness after GPU geometry and native UI composition.
CHANGES += (
 ('runtime/gpu2d/src/capture_origin.h',
  '    std::array<std::uint64_t,kScreenWidth> scene_a{},scene_b{};',
  '''    std::array<std::uint64_t,kScreenWidth> scene_a{},scene_b{};
    std::array<std::uint64_t,kScreenWidth> scene_origins_a{},scene_origins_b{};
    std::array<std::uint64_t,kPixelsPerFrame> scene_origins_top{},scene_origins_bottom{};''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '        if(scene_line)std::fill_n(scene_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);',
  '''        if(scene_line)std::fill_n(scene_line,kScreenWidth,kForegroundKnown|kForegroundInvalid);
        auto* scene_origin_line=origins?(is_a?origins->scene_origins_a.data():origins->scene_origins_b.data()):nullptr;
        if(scene_origin_line)std::fill_n(scene_origin_line,kScreenWidth,0);''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '                scene_line[xi]=normal_display?dst_foreground:kForegroundKnown|kForegroundInvalid;',
  '''                scene_line[xi]=normal_display?dst_foreground:kForegroundKnown|kForegroundInvalid;
                scene_origin_line[xi]=normal_display?dst_origin:0;''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '                if(scene_line)for(unsigned x=0;x<kScreenWidth;++x){const auto fg=lcdc_foreground(bank,y*512U+x*2U);scene_line[x]=fg?fg:native_foreground(output[x]);}',
  '''                if(scene_line)for(unsigned x=0;x<kScreenWidth;++x){const auto fg=lcdc_foreground(bank,y*512U+x*2U);scene_line[x]=fg?fg:native_foreground(output[x]);scene_origin_line[x]=lcdc_origin(bank,y*512U+x*2U);}''',2),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '            origins->brightness_bottom[y]=a_on_top?origins->brightness_b:origins->brightness_a;',
  '''            origins->brightness_bottom[y]=a_on_top?origins->brightness_b:origins->brightness_a;
            std::copy_n(a_on_top?origins->scene_origins_a.data():origins->scene_origins_b.data(),kScreenWidth,origins->scene_origins_top.data()+row);
            std::copy_n(a_on_top?origins->scene_origins_b.data():origins->scene_origins_a.data(),kScreenWidth,origins->scene_origins_bottom.data()+row);''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '            origins->scene_a.fill(0);origins->scene_b.fill(0);origins->scene_top.fill(0);origins->scene_bottom.fill(0);',
  '''            origins->scene_a.fill(0);origins->scene_b.fill(0);origins->scene_top.fill(0);origins->scene_bottom.fill(0);
            origins->scene_origins_a.fill(0);origins->scene_origins_b.fill(0);origins->scene_origins_top.fill(0);origins->scene_origins_bottom.fill(0);''',1),
 ('runtime/gpu2d/src/gpu2d.cpp',
  '    visit(impl_->origins->top); visit(impl_->origins->bottom);',
  '''    visit(impl_->origins->top); visit(impl_->origins->bottom);
    visit(impl_->origins->scene_origins_top); visit(impl_->origins->scene_origins_bottom);''',1),
 ('runtime/include/dsr/gpu2d.h',
  '    const std::uint64_t* screen_top_scene_foreground() const;',
  '''    // Raster IDs before master brightness; use with scene foreground and
    // per-line brightness, never as final-colour replacement eligibility.
    const std::uint64_t* screen_top_scene_origins() const;
    const std::uint64_t* screen_bottom_scene_origins() const;
    const std::uint64_t* screen_top_scene_foreground() const;''',1),
)

METHODS='''
namespace dsr {
const std::uint64_t* Gpu2D::screen_top_scene_origins() const {return impl_->origins?impl_->origins->scene_origins_top.data():nullptr;}
const std::uint64_t* Gpu2D::screen_bottom_scene_origins() const {return impl_->origins?impl_->origins->scene_origins_bottom.data():nullptr;}
const std::uint64_t* Gpu2D::screen_top_scene_foreground() const {return impl_->origins?impl_->origins->scene_top.data():nullptr;}
const std::uint64_t* Gpu2D::screen_bottom_scene_foreground() const {return impl_->origins?impl_->origins->scene_bottom.data():nullptr;}
const std::uint8_t* Gpu2D::screen_top_brightness() const {return impl_->origins?impl_->origins->brightness_top.data():nullptr;}
const std::uint8_t* Gpu2D::screen_bottom_brightness() const {return impl_->origins?impl_->origins->brightness_bottom.data():nullptr;}
}
'''


def patch(root):
    root=Path(root)
    for name,before,after,count in CHANGES:
        p=root/name;p.write_text(replace(p.read_text(encoding='utf-8'),before,after,count),encoding='utf-8')
    p=root/'runtime/gpu2d/src/gpu2d.cpp';p.write_text(p.read_text(encoding='utf-8')+METHODS,encoding='utf-8')
