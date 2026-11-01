# Project-owned DS features

A generated native game may add `native/project_features.hpp` to define
`ds_project::Features`. The generic exporter supplies no game-specific patches
or content data. This optional file belongs to the game project and is not
replaced by regeneration.

The host constructs one feature object, then invokes:

- `start(dsr::Session&, const dsr::MachineConfig&)` after profile initialization,
  under the save lock and before the first step. Existing pre-start save restore
  APIs are available here.
- `frame(dsr::Session&, const dsr::InputState&)` after each completed gameplay
  frame, before the periodic save flush. Settings pauses do not invoke it.
- `input(dsr::Session&, dsr::InputState&)` after host input polling and before
  stepping. It may filter input for project UI; returning false stops gameplay.
- `report(std::ostream&) const` while writing the final diagnostics object.
  A feature can append comma-prefixed JSON members, or write nothing.

All methods are required. Without the optional header, the hooks do nothing and
the diagnostics object retains its existing fields. They do not depend on cheat
catalogs, menu toggles or command-line activation. Game projects must validate
their ROM revision, data layout, persistence and progression behavior.
