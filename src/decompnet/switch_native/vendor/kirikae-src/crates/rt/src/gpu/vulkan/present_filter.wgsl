struct SourceTransform {
    scale: vec2<f32>,
    origin: vec2<f32>,
    bounds: vec4<i32>,
}

@group(0) @binding(0) var source: texture_2d<f32>;
var<immediate> transform: SourceTransform;

@vertex
fn vertex_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    let corner = vec2<f32>(f32(index & 1u), f32(index >> 1u));
    return vec4<f32>(corner * 4.0 - 1.0, 0.0, 1.0);
}

fn cubic_weights(t: f32) -> vec4<f32> {
    let t2 = t * t;
    let t3 = t2 * t;
    return vec4<f32>(
        -0.5 * t + t2 - 0.5 * t3,
        1.0 - 2.5 * t2 + 1.5 * t3,
        0.5 * t + 2.0 * t2 - 1.5 * t3,
        -0.5 * t2 + 0.5 * t3,
    );
}

fn load_row(x: vec4<i32>, y: i32) -> mat4x4<f32> {
    return mat4x4<f32>(
        textureLoad(source, vec2<i32>(x.x, y), 0),
        textureLoad(source, vec2<i32>(x.y, y), 0),
        textureLoad(source, vec2<i32>(x.z, y), 0),
        textureLoad(source, vec2<i32>(x.w, y), 0),
    );
}

@fragment
fn fragment_main(@builtin(position) position: vec4<f32>) -> @location(0) vec4<f32> {
    // Replicate the visible crop's edges without sampling producer padding.
    let pixel = position.xy * transform.scale + transform.origin - 0.5;
    let base = vec2<i32>(floor(pixel));
    let taps = vec4<i32>(-1, 0, 1, 2);
    let x = clamp(vec4<i32>(base.x) + taps, vec4<i32>(transform.bounds.x), vec4<i32>(transform.bounds.z));
    let y = clamp(vec4<i32>(base.y) + taps, vec4<i32>(transform.bounds.y), vec4<i32>(transform.bounds.w));
    let fraction = fract(pixel);
    let wx = cubic_weights(fraction.x);
    let wy = cubic_weights(fraction.y);
    let row0 = load_row(x, y.x);
    let row1 = load_row(x, y.y);
    let row2 = load_row(x, y.z);
    let row3 = load_row(x, y.w);
    let rows = mat4x4<f32>(row0 * wx, row1 * wx, row2 * wx, row3 * wx);
    let color = (rows * wy).rgb;

    // The central four texels bound local contrast, limiting ringing at HUD edges.
    let low = min(min(row1[1].rgb, row1[2].rgb), min(row2[1].rgb, row2[2].rgb));
    let high = max(max(row1[1].rgb, row1[2].rgb), max(row2[1].rgb, row2[2].rgb));
    let alpha_top = mix(row1[1].a, row1[2].a, fraction.x);
    let alpha_bottom = mix(row2[1].a, row2[2].a, fraction.x);
    return vec4<f32>(clamp(color, low, high), mix(alpha_top, alpha_bottom, fraction.y));
}
