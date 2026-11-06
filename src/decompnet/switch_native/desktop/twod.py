"""Match Maxwell 2D point copies to Vulkan's integer blit rectangles."""


def point_copy(root):
    from .patches import replace_once

    source = root / 'crates/rt/src/gpu/twod.rs'
    replace_once(source, 'impl Gpu {', '''fn source_rect(
    source: [f64; 2], step: [f64; 2], destination: [i32; 4],
    source_extent: [u32; 2], destination_extent: [u32; 2], sample_mode: u32,
) -> [f32; 4] {
    let size = [destination[2] - destination[0], destination[3] - destination[1]];
    // NV902D corner-mode point coordinates describe sample positions within
    // texels. For unit steps their integer texel indices are exact blit edges.
    let texel = source.map(f64::floor);
    let exact = sample_mode & 0x11 == 1 && step == [1.0; 2] && (0..2).all(|axis| {
        size[axis] > 0 && destination[axis] >= 0
            && i64::from(destination[axis + 2]) <= i64::from(destination_extent[axis])
            && texel[axis] >= 0.0 && texel[axis] + f64::from(size[axis]) <= f64::from(source_extent[axis])
    });
    // Other operations still use the existing scaled blit path. Normalizing
    // clipped rectangles independently would change the source/dest ratio.
    let [x, y] = if exact { texel } else { source };
    [x as f32, y as f32, (x + f64::from(size[0]) * step[0]) as f32,
     (y + f64::from(size[1]) * step[1]) as f32]
}

impl Gpu {''')
    replace_once(source, '''        let src_rect = [sx as f32, sy as f32, (sx + dw as f64 * du_dx) as f32, (sy + dh as f64 * dv_dy) as f32];
        let dst_rect = [dx, dy, dx + dw, dy + dh];
        let linear = regs[0x223] >> 4 & 1 == 1;''', '''        let dst_rect = [dx, dy, dx + dw, dy + dh];
        let sample_mode = regs[0x223];
        let src_rect = source_rect([sx, sy], [du_dx, dv_dy], dst_rect,
                                   [src.width, src.height], [dst.width, dst.height], sample_mode);
        let linear = sample_mode & 0x10 != 0;''')
    with source.open('a', encoding='utf-8', newline='\n') as out:
        out.write('''
#[cfg(test)]
mod tests {
    use super::source_rect;

    #[test]
    fn point_copy_preserves_texel_alignment_in_corner_mode() {
        let rect = |source, step, destination, mode| {
            source_rect(source, step, destination, [16, 8], [16, 8], mode)
        };
        assert_eq!(rect([0.5, 0.5], [1.0; 2], [0, 0, 16, 8], 1), [0.0, 0.0, 16.0, 8.0]);
        assert_eq!(rect([2.75, 1.5], [1.0; 2], [3, 2, 7, 5], 1), [2.0, 1.0, 6.0, 4.0]);
        assert_eq!(rect([0.5, 0.5], [1.0; 2], [0, 0, 16, 8], 0), [0.5, 0.5, 16.5, 8.5]);
        assert_eq!(rect([0.5, 0.5], [1.0; 2], [0, 0, 16, 8], 0x11), [0.5, 0.5, 16.5, 8.5]);
        assert_eq!(rect([0.5, 0.5], [0.5, 1.0], [0, 0, 16, 8], 1), [0.5, 0.5, 8.5, 8.5]);
        assert_eq!(rect([15.5, 0.5], [-1.0, 1.0], [0, 0, 16, 8], 1), [15.5, 0.5, -0.5, 8.5]);
        assert_eq!(rect([1.5, 0.5], [1.0; 2], [0, 0, 16, 8], 1), [1.5, 0.5, 17.5, 8.5]);
        assert_eq!(rect([0.5, 0.5], [1.0; 2], [-1, 0, 15, 8], 1), [0.5, 0.5, 16.5, 8.5]);
    }
}
''')
