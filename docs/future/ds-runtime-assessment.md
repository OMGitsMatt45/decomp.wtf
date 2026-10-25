# DQIV Recompiled: DS backend assessment

Reviewed on 2026-10-23 against [release 1.5](https://github.com/GoldieLeGenie/DQIV-Recompiled/releases/tag/1.5),
whose tag resolves to commit `d33f26238e2f1ede995ca55cebccbf7ec8af15fe`.
This is a source/interface review, not a successful local build or gameplay test.
No upstream game, SDK or runtime implementation is copied into decomp.wtf.

## What produces its PC game

The [build](https://github.com/GoldieLeGenie/DQIV-Recompiled/blob/d33f26238e2f1ede995ca55cebccbf7ec8af15fe/CMakeLists.txt)
compiles the existing decompiled `game/src/*.cpp` sources together with native
replacements for SDK/platform services. The owner's European YIVP ROM supplies
assets; the build does not translate an arbitrary input ROM's ARM instructions
into those C++ game sources. Its execution model maps to our `native-source`
contract. This is a useful product reference and a source-port architecture,
rather than a ready-made general ROM-to-PC adapter.

| Area | Observed interface | Consequence for decomp.wtf |
| --- | --- | --- |
| Game entry | `native/GameBoot.cpp` includes `GameApplication.hpp`, `GlobalDQ4.hpp` and achievement hooks | Boot and application bindings are title-specific. |
| Graphics | `NitroVideo`, `GxGeometry`, textures, rasterizer and an OpenGL renderer | Potential reusable service boundaries; rendering/presentation also contains title-specific behavior. |
| Sound | `NitroSound` connects SDK commands to native voices/sequences/mixing and named game globals | An SDK API replacement, not a general ARM7 CPU implementation. Raw ARM7 programs need a separate execution path. |
| Threads | `NitroThreads.cpp` uses Windows fibers and SDK thread/mutex structures | Depends on SDK ABI/layout and Windows scheduling support. |
| Overlays | CMake registers known modules 0–37 and the main module; `NitroOverlays` restores host sections and runs constructors/destructors | Does not discover or execute arbitrary ROM overlay binaries. Preserve loader identities and lifecycle when translating another title. |
| OS services | `NitroOs.cpp` supplies SDK functions and address-named replacements such as `func_02079bf0` | Needs explicit bindings for each source/runtime interface; guest addresses are not portable symbol identities. |
| Host build | Win32 pointer-size requirement, MSVC linker sections and Windows APIs | Existing resource pointers assume 32-bit addresses. Linux/64-bit support requires deliberate pointer and platform handling. |
| Dependencies | SDL 3.4.16 archive hash and a pinned stb_vorbis source/hash | Preserve reproducible dependency identities in any adopted adapter. |

The [README](https://github.com/GoldieLeGenie/DQIV-Recompiled/blob/d33f26238e2f1ede995ca55cebccbf7ec8af15fe/README.md)
also separates required DS assets from optional Android audio data. A generic
adapter must not require another title's optional enhancement assets.

## Reuse decision

Keep the runtime/source boundary as the reference design, with two distinct
routes to the same PC-project contract:

1. An existing-source adapter can build a known compatible source port, identify
   its supported input hashes, pin the source/runtime and extract the owner's
   assets. This can reduce work for an already decompiled title. It does not
   establish support for DQV, Pokémon or another game automatically.
2. A general DS binary adapter needs an ARM9/ARM7 translator, guest memory and
   indirect-call/overlay dispatch, plus console services. Reuse title-independent
   runtime pieces where appropriate; use SDK replacements only for identified
   calls with verified ABI behavior. Preserve executable ARM7 code unless an
   explicitly supported service replacement supplies its behavior.

The reviewed tree has no LICENSE/COPYING/NOTICE file and the repository API
reports no detected license. Do not vendor its implementation or bundled SDK
sources as an adopted dependency until redistribution terms are established.
The interface assessment and our own original execution fixtures can proceed.

## Next implementation evidence

- Define the guest-address/host-pointer boundary and an explicit host architecture
  requirement; do not cast DS addresses directly to 64-bit host pointers.
- Generate host C/C++ from an original ARM/Thumb fixture through the intended
  execution backend, with indirect dispatch, two processors and an overlay change.
- Connect observable memory/interrupt/file/save behavior before adding graphics
  and audio qualification. A prewritten host-only sample does not satisfy this.
- Keep source-native integration and binary translation as separate adapters with
  separate compatibility records. Disclose interpreter/runtime-compilation use.

No DS native adapter is registered by this assessment. The common foundation's
successful host fixture remains separate from DS execution and retail coverage.
