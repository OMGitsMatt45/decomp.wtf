# Optional dynamic widescreen presentation

Generated DS projects keep their two-LCD layout by default. A project can opt
into the original MIT host presentation implementation through its optional
`Features::configure_video(video::Options&)` method:

```cpp
#ifdef NDS_WITH_SDL
void configure_video(video::Options& options) {
    options.dynamic_widescreen = true;
    options.expand_visibility = true;
}
#endif
```

The host keeps the vertical field of view and fits the perspective scene to
the drawable aspect, up to 4:1. It renders the world at the existing default
12 native vertical multiples, bounded by the GPU texture size. Flat full-screen
backgrounds fill the canvas; orthographic UI is composed separately. Windows
move right, full-width dialogue is centered below, the other LCD is inset at
the upper left, and detected native party frames sit at the lower left. Native
2D pixels retain nearest filtering. Framed standalone pages stay 4:3. Movies,
portrait windows and unsupported capture compositions keep both complete LCDs.

Touch regions use inverse transforms to the original lower-LCD coordinates.
The upper LCD blocks touch-through. Enlarging the field does not add an input
queue or advance a guest frame. Master brightness is applied after composing
the world and foreground; unsupported scanline brightness retains the LCD view.

`Gpu3D::set_host_widescreen(aspect, expand_visibility)` observes primitives
before native clipping into independent bounded buffers (65,532 vertices,
16,383 polygons). The observer clips against the wider frustum, owns copies
at SWAP_BUFFERS, preserves projection metadata and native draw sorting, and
never consumes native geometry RAM or changes its overflow flags. Its aspect
configuration survives reset; its observed geometry does not. Native capture,
GX timing, hardware limits and BOX_TEST remain unchanged when visibility
expansion is false. With expansion true, perspective BOX_TEST deliberately
uses the wider horizontal frustum so the game submits side objects. This can
change guest execution; it must not be described as guest-state-equivalent.

The presentation follows actual raster identities through display captures
and CPU copies. Only identity mappings with supported foreground composition
are rearranged. Unsupported/ambiguous mappings retain the ordinary presentation.
Projection classification uses the submitted matrix, not constant vertex W.

This is a heuristic interface layout, not a semantic parser of every game's
menus. Projects should qualify field, dialogue, submenus, battle, touch, saves
and frame pacing before enabling it by default. Original synthetic regression
scenes cover side-only primitives, independent hardware counts, opt-in object
visibility, orthographic exclusion, reset ownership, UI inverse mapping, one
through four party rows, 4:3 pages, movies and live ultrawide resizing.

DQIX Enhanced's public README/STATE documentation informed the behavioral
target. No GPL implementation code or game assets were copied into this MIT
runtime implementation.
