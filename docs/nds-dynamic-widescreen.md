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
2D pixels retain nearest filtering. Framed standalone pages stay 4:3, including
enhanced captured 3D previews. Two active menu screens with captured 3D are shown
side by side in landscape, at 4:3 each. Synchronized movie streams retain their
original vertical relationship. Portrait windows retain the stacked pair.

The initial window opens at 16:9. A startup picture can occupy the full height
with a sparse second-LCD Start prompt overlaid below. Its original button pixels
and lower-LCD touch coordinates are retained. Movies keep their source detail
and aspect rather than being stretched. Battle messages move clear of party
panels; split far-depth sky gradients remain on the world canvas.

A one-screen cinematic with an empty second LCD keeps its authored 4:3 frustum,
enhanced 3D, and complete native narration together. It has no empty map inset
and its individual glyphs are never relocated as separate windows. Captured
3D also follows LCD master brightness per row, including full fade endpoints.

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

Projects that can identify game states may optionally implement
`Features::configure_frame(dsr::Session&, video::Frame&)`. The host calls it
immediately before presenting the current frame. Its `mode` defaults to `Auto`;
`Gameplay` retains world/HUD composition during menu and battle fades,
`MovieVertical` keeps both original LCDs in one fixed vertical composition,
and `MenuLandscape` keeps a paired menu in landscape even with tall page
frames. `MovieSingle` uses the original 4:3 image from the LCD selected by
`Frame::on_top`, with side bars, including during entirely blank movie frames.
These hints do not change the native pixels or guest execution.
`auxiliary` can identify a `Map`, `Battle` panel or `Hidden` secondary LCD.
For example, explicit battle context prevents an empty results backdrop from
being displayed as a map. Projects own state detection and movie lifetimes.

Unframed foreground sprites keep their native world projection regardless of
animation size or height. Bounded frames and lower captions use the smaller
HUD scale; a choice window touching its dialogue remains one group. Party and
results panels retain native touch coordinates while cropping outside border
margins. Optional `Frame::hud_regions` identify fixed buttons by native bounds
and source LCD; these stay at HUD scale while other unframed sprites follow
the world. Projects must identify their buttons rather than treating every
small sprite as a fixed HUD element. A gameplay frame without replayable geometry uses its current native
primary LCD and background color rather than promoting its map to the main
picture. It cannot synthesize geometry missing from that frame.

DQIX Enhanced's public README/STATE documentation informed the behavioral
target. No GPL implementation code or game assets were copied into this MIT
runtime implementation.
