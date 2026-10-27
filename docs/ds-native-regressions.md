# DS native export regressions

Retail playthrough testing exposed two failures that original fixtures now cover.
These corrections apply to newly generated projects; existing outputs must be
regenerated from their original input. Generated projects continue to use static
C++ execution without an interpreter or runtime compiler.

The importer can classify referenced ARM9 callback bodies as data, including
Thumb leaves without a stack prologue. The exporter now follows aligned pointers
from declared data within the same module image and validates their ARM/Thumb
control flow with the normal translator. It rejects unsupported instructions,
conflicting code/literals and conflicting instruction modes, preserves literal
pools and switch tables, and records the recovered entries and pointer sources
in the manifest. Original tests exercise direct callees, conditional returns and
signed halfword dispatch tables.

Identical caller bytes can occur in multiple overlays whose callees differ.
Ambiguous direct targets now use the existing dispatch by the loaded target
bytes rather than binding to one overlay's C++ function. A two-overlay original
fixture verifies distinct results from identical callers.

The geometry runtime previously filled vertex and polygon RAM with off-screen
and culled scenery before receiving later objects. It now rejects invisible
primitives before storing their geometry. Original tests submit thousands of
rejected primitives followed by visible geometry, exercise triangle/quad strips
across rejected primitives and retain the finite RAM limits and overflow flags.
Partially clipped primitives use the pinned rasterizer's existing clipping path.

`ds_pc --dump-memory DIRECTORY` additionally captures raw OAM, palettes, all nine
VRAM banks, display registers and the most recently activated geometry. This
opt-in diagnostic contains input-derived data and belongs with private debugging
evidence. It records an end-of-frame snapshot, not a GX command trace or a claim
that all registers/mappings remained constant during the frame.
