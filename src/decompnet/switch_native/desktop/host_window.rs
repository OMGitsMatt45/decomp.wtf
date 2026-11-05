//! Size the initial window in physical pixels, inside the usable desktop.
use winit::{
    dpi::{LogicalSize, PhysicalPosition, PhysicalSize},
    event_loop::ActiveEventLoop,
    monitor::MonitorHandle,
    window::{Window, WindowAttributes},
};

pub fn attributes(el: &ActiveEventLoop, title: &str) -> WindowAttributes {
    let attrs = Window::default_attributes().with_title(title);
    let Some(monitor) = el.primary_monitor().or_else(|| el.available_monitors().next()) else {
        return attrs.with_inner_size(LogicalSize::new(1280.0, 720.0));
    };
    let (origin, area) = work_area(&monitor).unwrap_or_else(|| (monitor.position(), monitor.size()));
    let (position, size) = fit(origin, area, monitor.scale_factor());
    attrs.with_inner_size(size).with_position(position)
}

fn fit(
    origin: PhysicalPosition<i32>,
    area: PhysicalSize<u32>,
    scale: f64,
) -> (PhysicalPosition<i32>, PhysicalSize<u32>) {
    // Leave room for the non-client frame and title bar, including at high DPI.
    let reserve = (80.0 * scale).ceil() as u32;
    let units = ((80.0 * scale) as u32)
        .min(area.width.saturating_sub(reserve) / 16)
        .min(area.height.saturating_sub(reserve) / 9)
        .max(1);
    let size = PhysicalSize::new(16 * units, 9 * units);
    let position = PhysicalPosition::new(
        origin.x + (area.width.saturating_sub(size.width) / 2) as i32,
        origin.y + (area.height.saturating_sub(size.height) / 3) as i32,
    );
    (position, size)
}

#[cfg(windows)]
fn work_area(monitor: &MonitorHandle) -> Option<(PhysicalPosition<i32>, PhysicalSize<u32>)> {
    use std::ffi::c_void;
    use winit::platform::windows::MonitorHandleExtWindows;

    #[repr(C)]
    struct MonitorInfo {
        size: u32,
        monitor: [i32; 4],
        work: [i32; 4],
        flags: u32,
    }
    #[link(name = "user32")]
    unsafe extern "system" {
        fn GetMonitorInfoW(monitor: *mut c_void, info: *mut MonitorInfo) -> i32;
    }
    let mut info = MonitorInfo {
        size: std::mem::size_of::<MonitorInfo>() as u32,
        monitor: [0; 4],
        work: [0; 4],
        flags: 0,
    };
    if unsafe { GetMonitorInfoW(monitor.hmonitor() as *mut c_void, &mut info) } == 0 {
        return None;
    }
    let [left, top, right, bottom] = info.work;
    let width = u32::try_from(right.checked_sub(left)?).ok()?;
    let height = u32::try_from(bottom.checked_sub(top)?).ok()?;
    (width > 0 && height > 0)
        .then(|| (PhysicalPosition::new(left, top), PhysicalSize::new(width, height)))
}

#[cfg(not(windows))]
fn work_area(_monitor: &MonitorHandle) -> Option<(PhysicalPosition<i32>, PhysicalSize<u32>)> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn high_dpi_window_reserves_space_for_decorations() {
        let origin = PhysicalPosition::new(-1920, 40);
        let (at, size) = fit(origin, PhysicalSize::new(1920, 1000), 1.5);
        assert!(at.x >= origin.x && at.y >= origin.y);
        assert!(at.x + size.width as i32 + 24 <= 0);
        assert!(at.y + size.height as i32 + 60 <= 1040);
        assert_eq!(size.width * 9, size.height * 16);
    }
}
