//! Resolution-independent screen composition and touch mapping. MIT.
//! This composes the game's pictures; joining two independent game cameras
//! requires title-specific scene knowledge and must not be guessed here.
use super::Viewport;

fn fit(width: f32, height: f32, aspect: f32) -> Viewport {
    let w = width.min(height * aspect);
    let h = w / aspect;
    Viewport { x: (width-w)/2.0, y: (height-h)/2.0, width: w, height: h }
}

pub fn places(width: u32, height: u32, bottom_primary: bool) -> (Option<Viewport>, Option<Viewport>) {
    if width == 0 || height == 0 { return (None, None); }
    let (w,h) = (width as f32, height as f32);
    let main = fit(w,h,if bottom_primary {320.0/240.0} else {400.0/240.0});
    let margin = 16.0_f32.min(w.min(h)/32.0);
    let mut inset = fit((w-2.0*margin).min(w/3.0), (h-2.0*margin).min(h/4.0),
        if bottom_primary {400.0/240.0} else {320.0/240.0});
    inset.x = w-inset.width-margin;
    inset.y = h-inset.height-margin;
    if bottom_primary {(Some(inset),Some(main))} else {(Some(main),Some(inset))}
}

/// Physical drawable coordinates, not logical window coordinates. Ignore
/// letterboxing and the top picture when it overlays the touch screen.
pub fn touch(top: Option<Viewport>, bottom: Option<Viewport>, bottom_primary: bool,
    x:f64, y:f64) -> Option<(u16,u16)> {
    let inside = |v:Viewport| x>=v.x as f64 && y>=v.y as f64
        && x<(v.x+v.width) as f64 && y<(v.y+v.height) as f64;
    if bottom_primary && top.is_some_and(inside) { return None; }
    let v=bottom.filter(|v|v.width>0.0 && v.height>0.0 && inside(*v))?;
    Some((((x-v.x as f64)*320.0/v.width as f64).floor().clamp(0.0,319.0) as u16,
        ((y-v.y as f64)*240.0/v.height as f64).floor().clamp(0.0,239.0) as u16))
}
