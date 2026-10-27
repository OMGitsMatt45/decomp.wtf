# Five-console PC output check

Owner-supplied retail inputs were exported without reviewed profiles or runtime
feedback lists, built, and run in bounded tests. Generated game code, original
media, BIOS dumps, input hashes, captures and private diagnostics remain outside
the repository. Full playthrough acceptance belongs to the owner.

This table records the initial five-console run. Subsequent strict static
execution checks supersede its PS1, PS2 and GBA fallback observations: see
[PS1 native validation](ps1-native-validation.json) and
[PS2 native validation](ps2-native-validation.json), plus
[GBA native validation](gba-static-validation.json). The historical counts below
remain unchanged so the original assessment can be distinguished from later work.

| Platform and sample | Observed result | Execution scope |
| --- | --- | --- |
| DS, Pokémon Platinum | Normal export produced 34,788 ARM9 and 1,140 ARM7 functions. The native build completed 1,800 OpenGL frames with nonzero audio samples and zero unsupported IO accesses. | Static CPUs; the captured intro uses 2D presentation. Original fixtures separately exercise GPU geometry, touch, IRQs, audio and saves. |
| PS1, Dragon Warrior VII | One source project and executable ran disc 1 for 1,800 frames and disc 2 for 600 frames through OpenGL. | Hybrid execution; both native dispatch and interpreted instruction counts are retained. Original fixtures exercise different disc code, tray changes and shared saves. |
| PS2, Dragon Quest VIII | Fresh source built and completed 120 seconds through Vulkan: 1,998 presented frames, approximately 1.75 million primitives, visible game settings, and zero missing EE functions or execution failures. | Statically translated EE; IOP and VU interpretation remain explicit. |
| GBA, Pokémon Emerald | Fresh automatic export ran 2,400 OpenGL frames with the owner's BIOS and deterministic RTC. Frame, cycle, audio and screen results matched the interpreter reference. | Hybrid: 332 translated functions, 416 recorded misses, and interpreted cycles including BIOS execution. This automatic run does not establish fully static Emerald coverage. |
| 3DS, Dragon Quest VII | Automatic native output reached the title in 2,231 frames, executing over 662 million native instructions with no interpreted instructions or unresolved calls/services. Vulkan and software runs agreed with the independent reference picture. | Strict static CPU execution for the tested path; broader retail coverage remains experimental. Fresh merged-main export matched all 318 previously compiled source/configuration files and was boot-checked. |

Cloud graphics used Mesa llvmpipe. These runs exercise actual OpenGL/Vulkan
paths, but do not qualify a physical GPU or its performance. Windows physical
3DS qualification is available through `tools/qualify-3ds-hardware.ps1`; the
script retains its assessment and logs. Earlier owner-run PS2 and GBA original
fixtures qualified Intel Iris Xe hardware separately.
The subsequent [owner-run 3DS result](3ds-hardware-validation.json) also passed
the four original Vulkan scenes and the stacked-screen window on Windows 11 /
Intel Iris Xe. This adds physical fixture evidence without changing the bounded
retail or full-playthrough scope above.

An additional unchanged European DQIV export generated 13,570 ARM9 and 1,059
ARM7 functions and reached its title in 1,800 static frames. Its headless and
OpenGL guest screen hashes agreed after wireless RAM was modeled correctly.
There are still 67 unsupported wireless wait/MAC register diagnostics; this is
an offline title check, not wireless qualification or full gameplay acceptance.
Guarded graphics effects retain the native DS raster picture for this title
sequence. The supplied US-only party-chat patch was not applied to the European
input. Mobile enhancements require separate game-output integration.

## Comparison with DQIV Recompiled

The reference is [GoldieLeGenie/DQIV-Recompiled](https://github.com/GoldieLeGenie/DQIV-Recompiled/tree/c1cf527ce51b888aa5a684fe9cae90123fc93667).
The common deliverable is a source repository containing game code, native
runtime/platform code, a CMake host build, dependency pins, asset preparation,
run instructions and save handling. The exported projects supply that structure
and run independently of the decomp.wtf Python application after building.

Goldie's project contains a manually adapted, named C++ game engine and a
32-bit Windows platform layer. Automatic static translation preserves machine
code behavior and guest memory; it does not reconstruct that source-level
architecture. Hybrid backends additionally retain their declared interpreters.
Successful bounded execution must not be presented as complete source recovery.

Goldie's continuous camera, mobile music, party chat, interpolation, settings
and other enhancements are separate game-output work. The generic DS and 3DS
outputs retain both original screens. This check establishes no feature-parity
claim, and no Goldie game implementation was adopted or relabeled as generated
output. See the [PC output contract](pc-output.md) for the acceptance boundary.
