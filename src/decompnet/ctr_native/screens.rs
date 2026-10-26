//! Touch coordinates in the original lower LCD. MIT.
use zakuro_gpu::backend::Viewport;

pub fn touch(bottom: Option<Viewport>, x:f64, y:f64) -> Option<(u16,u16)> {
    let v=bottom.filter(|v|v.width>0.0 && v.height>0.0 && x>=v.x as f64 && y>=v.y as f64
        && x<(v.x+v.width) as f64 && y<(v.y+v.height) as f64)?;
    Some((((x-v.x as f64)*320.0/v.width as f64).floor().clamp(0.0,319.0) as u16,
        ((y-v.y as f64)*240.0/v.height as f64).floor().clamp(0.0,239.0) as u16))
}
