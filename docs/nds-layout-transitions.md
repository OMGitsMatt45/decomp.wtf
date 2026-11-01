# DS presentation during scene transitions

Dynamic widescreen must distinguish an authored two-LCD movie from a menu,
startup picture or single-LCD cinematic whose metadata changes during a fade.
Layout observations do not change guest pixels, execution or input timing.

Bounded menu frames are classified using complete, known, opaque 2D foreground
metadata before LCD master brightness when available. Partial or unsupported
metadata falls back to the native picture. Rendering still uses the current
displayed pixels: classification must never reveal an unfaded foreground.

A sparse Start prompt takes precedence over long bright lines in movie art.
Once startup framing is established, an empty picture behind the live prompt or
a removed prompt beside the remaining picture retains that framing. A real
two-screen picture replaces it immediately. Nearly blank asynchronous credit
fades preserve only their previous single/paired framing, never previous pixels.

During cinematic cuts, a blank black or white secondary LCD does not create an
empty second pane. If replayable world polygons temporarily disappear, the
complete current native picture remains in its single-screen frame, with any
safe captured enhancement and native lower-LCD touch mapping. Two populated
movie screens still select their original vertical composition immediately.

There is no frame-count debounce, delayed guest frame or cached screenshot.
The original GPU fixture covers all 17 darken/brighten levels, unsupported and
partial metadata, false movie border hints, prompt removal, asynchronous credit
fades, missing cinematic geometry/origins, mixed black/white LCDs, touch, and an
immediate return to genuine two-screen movies. Large classification/mask buffers
belong to the heap-owned display rather than nested presentation stack frames.
