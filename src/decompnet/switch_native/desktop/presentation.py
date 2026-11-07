"""Present the source rectangle requested by the Switch buffer producer."""


def buffer_crop(root):
    from .patches import replace_once

    rt = root / 'crates/rt/src'
    replace_once(rt / 'display.rs', 'pub static FRAMES: AtomicU64', '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BufferCrop {
    pub(crate) left: u32,
    pub(crate) top: u32,
    pub(crate) right: u32,
    pub(crate) bottom: u32,
}

impl BufferCrop {
    pub(crate) fn full(width: u32, height: u32) -> Self {
        Self { left: 0, top: 0, right: width, bottom: height }
    }

    pub(crate) fn checked(rect: [i32; 4], width: u32, height: u32) -> Self {
        let [left, top, right, bottom] = rect;
        if left < 0 || top < 0 || right <= left || bottom <= top || right as u32 > width || bottom as u32 > height {
            return Self::full(width, height);
        }
        Self { left: left as u32, top: top as u32, right: right as u32, bottom: bottom as u32 }
    }

    pub(crate) fn apply(self, mut frame: Frame) -> Frame {
        if self == Self::full(frame.width, frame.height) {
            return frame;
        }
        let width = (self.right - self.left) as usize;
        for (out, y) in (self.top..self.bottom).enumerate() {
            let start = (y * frame.width + self.left) as usize;
            frame.pixels.copy_within(start..start + width, out * width);
        }
        frame.width = width as u32;
        frame.height = self.bottom - self.top;
        frame.pixels.truncate(width * frame.height as usize);
        frame
    }
}

// Fit the visible guest frame into the host drawable using physical pixels.
pub(crate) fn fit_frame(source: [u32; 2], destination: [u32; 2]) -> [u32; 4] {
    let [sw, sh] = source.map(u64::from);
    let [dw, dh] = destination.map(u64::from);
    let (w, h) = if sw * dh > sh * dw {
        (dw, (dw * sh / sw).max(1))
    } else {
        ((dh * sw / sh).max(1), dh)
    };
    [(dw - w) as u32 / 2, (dh - h) as u32 / 2, w as u32, h as u32]
}

#[cfg(test)]
mod fit_tests {
    use super::fit_frame;

    #[test]
    fn centers_the_visible_frame_without_stretching() {
        assert_eq!(fit_frame([1280, 720], [1920, 1080]), [0, 0, 1920, 1080]);
        assert_eq!(fit_frame([1280, 720], [1920, 1200]), [0, 60, 1920, 1080]);
        assert_eq!(fit_frame([1280, 720], [3440, 1440]), [440, 0, 2560, 1440]);
        assert_eq!(fit_frame([1280, 720], [1, 1]), [0, 0, 1, 1]);
    }
}

pub static FRAMES: AtomicU64''')

    replace_once(rt / 'display.rs', '''                for y in 0..dh {
                    let row = &f.pixels[(y * sh / dh) * sw..][..sw];
                    let out = &mut buf[y * dw..][..dw];
                    for (x, px) in out.iter_mut().enumerate() {
                        *px = row[x * sw / dw];
                    }
                }''', '''                let [left, top, width, height] = fit_frame([f.width, f.height], [size.width, size.height]).map(|n| n as usize);
                if width != dw || height != dh {
                    buf.fill(0);
                }
                for y in 0..height {
                    let row = &f.pixels[(y * sh / height) * sw..][..sw];
                    let out = &mut buf[(y + top) * dw + left..][..width];
                    for (x, px) in out.iter_mut().enumerate() {
                        *px = row[x * sw / width];
                    }
                }''')

    vi = rt / 'services/vi.rs'
    replace_once(vi, 'use crate::display::{self, Frame};', 'use crate::display::{self, BufferCrop, Frame};')
    replace_once(vi, '            let transform = word(40).unwrap_or(0);', '''            let crop = queue_crop(raw.as_deref().unwrap_or_default());
            let transform = word(40).unwrap_or(0);''')
    replace_once(vi, '                    present(p, &s, transform);', '                    present(p, &s, crop, transform);')
    replace_once(vi, 'fn present(p: &Process, s: &Slot, transform: u32) {', '''fn queue_crop(raw: &[u8]) -> [i32; 4] {
    // BqBufferInput has eight bytes of flattened-object header before its timestamp.
    [20, 24, 28, 32].map(|at| raw.get(at..at + 4).map_or(0, |word| i32::from_le_bytes(word.try_into().unwrap())))
}

fn present(p: &Process, s: &Slot, rect: [i32; 4], transform: u32) {
    let crop = BufferCrop::checked(rect, s.width, s.height);
    if crate::env_var!("KIRIKAE_STATS").is_some() {
        static LOGGED: Mutex<std::collections::BTreeSet<(u32, u32, [i32; 4])>> = Mutex::new(std::collections::BTreeSet::new());
        if LOGGED.lock().unwrap().insert((s.width, s.height, rect)) {
            eprintln!("kirikae: vi: buffer {}x{}, crop [left, top, right, bottom]={rect:?}, applied={crop:?}", s.width, s.height);
        }
    }''')
    replace_once(vi, 'map(|pixels| transformed(Frame { width: s.width, height: s.height, pixels }, transform));',
                 'map(|pixels| transformed(crop.apply(Frame { width: s.width, height: s.height, pixels }), transform));')
    replace_once(vi, 'p.gpu.present(cpu, s.width, s.height, flip_h, flip_v)',
                 'p.gpu.present(cpu, s.width, s.height, crop, flip_h, flip_v)')
    replace_once(vi, 'let frame = transformed(Frame { width: s.width, height: s.height, pixels }, transform);',
                 'let frame = transformed(crop.apply(Frame { width: s.width, height: s.height, pixels }), transform);')

    gpu = rt / 'gpu/mod.rs'
    replace_once(gpu, 'pub fn present(&self, cpu: u64, width: u32, height: u32, flip_h: bool, flip_v: bool)',
                 'pub fn present(&self, cpu: u64, width: u32, height: u32, crop: crate::display::BufferCrop, flip_h: bool, flip_v: bool)')
    replace_once(gpu, 'r.present(cpu, width, height, flip_h, flip_v)', 'r.present(cpu, width, height, crop, flip_h, flip_v)')

    present = rt / 'gpu/vulkan/present.rs'
    replace_once(present, 'use ash::vk;', 'use ash::vk;\n\nuse crate::display::{BufferCrop, fit_frame};')
    replace_once(present, 'pub fn present(&mut self, cpu: u64, width: u32, height: u32, flip_h: bool, flip_v: bool)',
                 'pub fn present(&mut self, cpu: u64, width: u32, height: u32, crop: BufferCrop, flip_h: bool, flip_v: bool)')
    replace_once(present, 'self.present_image(key, width, height, flip_h, flip_v)', 'self.present_image(key, crop, flip_h, flip_v)')
    replace_once(present, 'self.present_image(key, width, height, false, false)',
                 'self.present_image(key, BufferCrop::full(width, height), false, false)')
    replace_once(present, 'fn present_image(&mut self, key: ImageKey, width: u32, height: u32, flip_h: bool, flip_v: bool) -> Presented {',
                 '''fn present_image(&mut self, key: ImageKey, crop: BufferCrop, flip_h: bool, flip_v: bool) -> Presented {
        if crop.left >= crop.right || crop.top >= crop.bottom {
            return Presented::NoImage;
        }''')
    replace_once(present, '''        let visible = [width.min(key.width), height.min(key.height)];
        let cubic = if self.present_filter_cubic && sc.filter.is_some()''', '''        let visible = [crop.right - crop.left, crop.bottom - crop.top];
        let [left, top, width, height] = fit_frame(visible, [extent.width, extent.height]);
        let cubic = if self.present_filter_cubic && sc.filter.is_some()
            && crop == BufferCrop::full(key.width, key.height)
            && [width, height] == [extent.width, extent.height]''')
    replace_once(present, '.src_offsets([vk::Offset3D { x: 0, y: 0, z: 0 }, vk::Offset3D { x: w, y: h, z: 1 }])',
                 '''.src_offsets([
                        vk::Offset3D { x: crop.left as i32, y: crop.top as i32, z: 0 },
                        vk::Offset3D { x: crop.right as i32, y: crop.bottom as i32, z: 1 },
                    ])''')
    replace_once(present, '''                let [w, h] = visible.map(|v| v as i32);
                let (x0, x1) = if flip_h { (extent.width as i32, 0) } else { (0, extent.width as i32) };
                let (y0, y1) = if flip_v { (extent.height as i32, 0) } else { (0, extent.height as i32) };''', '''                let (left, top, right, bottom) = (left as i32, top as i32, (left + width) as i32, (top + height) as i32);
                let (x0, x1) = if flip_h { (right, left) } else { (left, right) };
                let (y0, y1) = if flip_v { (bottom, top) } else { (top, bottom) };''')
    replace_once(present, '                d.cmd_blit_image(self.cmd, self.images[&key].image,', '''                if width != extent.width || height != extent.height {
                    let black = vk::ClearColorValue { float32: [0.0, 0.0, 0.0, 1.0] };
                    d.cmd_clear_color_image(self.cmd, target, write_layout, &black, &[range]);
                    let written = [to_write[0].old_layout(write_layout).src_access_mask(write_access)];
                    d.cmd_pipeline_barrier(self.cmd, write_stage, write_stage, vk::DependencyFlags::empty(), &[], &[], &written);
                }
                d.cmd_blit_image(self.cmd, self.images[&key].image,''')

    replace_once(vi, '    #[test]\n    fn parcel_round_trip()', '''    #[test]
    fn queue_crop_uses_flattened_rect_and_precedes_flips() {
        let mut raw = [0u8; 56];
        for (at, value) in [(20, 1i32), (24, 1), (28, 4), (32, 3), (40, 2), (52, 1)] {
            raw[at..at + 4].copy_from_slice(&value.to_le_bytes());
        }
        assert_eq!(queue_crop(&raw), [1, 1, 4, 3]);
        let crop = BufferCrop::checked(queue_crop(&raw), 5, 4);
        let frame = || Frame { width: 5, height: 4, pixels: (0..20).collect() };
        let cropped = crop.apply(frame());
        assert_eq!((cropped.width, cropped.height), (3, 2));
        assert_eq!(cropped.pixels, [6, 7, 8, 11, 12, 13]);
        assert_eq!(transformed(crop.apply(frame()), TRANSFORM_FLIP_H).pixels, [8, 7, 6, 13, 12, 11]);
        assert_eq!(transformed(crop.apply(frame()), TRANSFORM_FLIP_V).pixels, [11, 12, 13, 6, 7, 8]);
    }

    #[test]
    fn queue_crop_defaults_to_full_buffer_for_invalid_rects() {
        let full = BufferCrop::full(1280, 720);
        for rect in [queue_crop(&[]), [-1, 0, 1280, 720], [3, 1, 3, 2], [0, 0, 1281, 720], [0, 0, 1280, 721]] {
            assert_eq!(BufferCrop::checked(rect, 1280, 720), full);
        }
        assert_eq!(BufferCrop::checked([0, 0, 1280, 720], 1920, 1080), full);
    }

    #[test]
    fn parcel_round_trip()''')
