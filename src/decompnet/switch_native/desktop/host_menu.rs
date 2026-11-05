//! Opt-in handoff to the launching application's PC settings menu.
use std::sync::atomic::{AtomicBool, Ordering};

pub static RETURNED_TO_SETTINGS: AtomicBool = AtomicBool::new(false);

fn enabled(value: Option<&str>, headless: bool) -> bool {
    value == Some("1") && !headless
}

pub fn confirm() -> bool {
    if !enabled(std::env::var("DECOMP_SWITCH_SETTINGS_MENU").ok().as_deref(), crate::display::headless()) {
        return false;
    }
    crate::input::release_all();
    let accepted = dialog();
    crate::input::release_all();
    if accepted { RETURNED_TO_SETTINGS.store(true, Ordering::Relaxed); }
    accepted
}

#[cfg(windows)]
fn dialog() -> bool {
    #[link(name = "user32")]
    unsafe extern "system" { fn MessageBoxW(window: isize, text: *const u16, caption: *const u16, kind: u32) -> i32; }
    let parent = match crate::display::window_handle() {
        Some(crate::display::WindowHandle::Win32 { hwnd, .. }) => hwnd,
        _ => 0,
    };
    let wide = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
    let title = wide("PC settings");
    let text = wide("Close the game and return to PC settings?\n\nSave from the game's menu first. Unsaved progress will be lost.\nChoose No to continue playing.");
    // MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2: continuing is the default.
    unsafe { MessageBoxW(parent, text.as_ptr(), title.as_ptr(), 0x124) == 6 }
}

#[cfg(not(windows))]
fn dialog() -> bool { false }

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn launcher_handoff_requires_explicit_interactive_opt_in() {
        for value in [None, Some(""), Some("0"), Some("true")] { assert!(!enabled(value, false)); }
        assert!(enabled(Some("1"), false));
        assert!(!enabled(Some("1"), true));
    }
}
