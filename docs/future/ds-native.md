# DS native PC-output backend

Status: **experimental static generator implemented in PR #29; retail runtime incomplete**.
Uses the shared application/output contract merged in PR #28. Merged PRs #1, #7
and #25 remain console reconstruction and source-recovery history; a successful
`.nds` rebuild or emulator execution is not this milestone.

The [DQIV 1.5 runtime assessment](ds-runtime-assessment.md) records the first
source/interface review and the boundary between a known source-port adapter and
a general DS binary translator. No DQIV implementation has been adopted. The
small integer/memory runtime is original MIT code. See its [generator guide](../nds-pc.md).

The additional [hardware-runtime adapter](../nds-native-runtime.md) now adopts
the separately reviewed MIT DQ9-Decomp runtime and emitter, pinned by commit and
archive hash. It analyzes DS inputs without matching compilers and ships native
runtime source in generated repositories. Original guest code verifies screens,
sound, IRQs, IPC, EEPROM reload, TCM controls, cartridge DMA and Thumb switches.
DQV retail testing now reaches name entry with DS audio; later
gameplay and save compatibility remain under active validation. No DQIV code or
mobile OBB dependency is adopted.

## Product

Given a supported owner-supplied DS game, generate one source project with a
host build and a DS runtime, producing a Windows application. DQIV Recompiled
1.5 is the product reference. Generic backend work should be reusable across DS
titles; title-specific configuration or fixes remain explicit. Original matching
compiler success is useful evidence, not a requirement to recover 100% readable
source before native translation can begin.

The deliverable is the repository itself: host-buildable game C/C++ in `game/`,
native platform/runtime integration in `native/`, CMake and pinned dependencies,
asset-extraction tools, and a README explaining inputs, build/run and saves. A
clean checkout with the documented original input must build the working PC game.
Follow the shared [repository acceptance target](../pc-output.md#generated-repository-acceptance-target).

## Implementation progress

1. **Source/interface assessment recorded.** Inspect the DQIV source/runtime interface and identify which parts are reusable
   console services and which are game-specific. Pin any adopted dependencies.
   Do not register a generic backend merely because that existing port builds.
2. **Experimental adapter implemented.** Implement one DS adapter using the common `decompnet.pc.Backend` interface.
   Consume reviewed ARM9/ARM7 and overlay facts from DS import. Preserve processor
   identity and ARM/Thumb entry modes; distinguish cartridge offsets from RAM
   addresses and initialized data from BSS. Retain compressed/protected loader
   facts rather than silently treating stored bytes as executable code. The
   current adapter requires reviewed ranges and rejects retail secure-area ARM9
   inputs, constructor execution and unsupported mappings. It remains outside
   the global backend registry and GUI.
3. **Original fixture implemented and executed.** Translate/execute an original fixture's ARM code through the intended native
   path. A prewritten host C++ sample only qualifies the common build contract.
   Include indirect calls, processor interaction and an overlay transition so
   the first test exercises code discovery beyond the boot executable. The
   fixture communicates between ARM9 and ARM7, calls Thumb code and replaces
   overlays at one address. Code ranges are reviewed explicitly; discovery is
   not automatic. Final registers, flags and memory are checked against original
   byte execution in Unicorn. Another 75 integer/shift cases cover edge behavior.
4. **Source-shipped hardware runtime integrated; retail qualification ongoing.** Qualify the DS memory/runtime interfaces: interrupts/timing, synchronization,
   2D/3D graphics, audio, input/touch, cartridge/files, save data and ARM7 services.
   Declare any interpreter or runtime-compilation fallback in the generated
   manifest; qualify static and hybrid output separately.
5. **Standalone repository generation and host execution implemented.** Generate a project from an original fixture, build it in a clean native
   Windows/Linux environment and execute it without a DS emulator process.
   Verify observable program output and deterministic save/reload state. The
   small-adapter save check persists a reviewed RAM region; the hardware adapter
   separately tests SPI EEPROM saves and reload. A
   dedicated Windows/Linux workflow exercises extraction, compilation, execution,
   save reload and clean rebuild without console tools or a DS emulator process.
6. **Pending.** Validate one agreed DQ or Pokémon title through boot/title/menu, rendering,
   sound/input, field/battle, overlay changes and save/reload. The user handles
   the eventual full playthrough. A different title requires compatibility
   validation, not another compiler or another exhaustive source-recovery pass.

## Output and qualification

Use `pc-project.json` schema `decomp.wtf.pc-project/v1`, pinned backend/runtime
identities, original input hashes, host C/C++ sources and CMake executable target.
Keep game assets private and extracted from the owner's input. Existing console
source projects remain separately buildable and are not renamed as PC ports.

Report these independently: import facts, source matching, project integrity,
native host build, native execution and retail compatibility. PR #28 supplies
the common contract; PR #29 begins a real static ARM/Thumb execution backend.
It has no interpreter or runtime compiler fallback. The hardware adapter now
supplies graphics, audio and save-device services and is exposed experimentally
in the application. A successful fixture is evidence for its tested CPU/runtime
path, not a claim that DS retail output is complete. Optional owner-supplied
mobile-remaster enhancements for DQ IV/V/VI follow native DS qualification;
the original DS sound remains a complete choice without an OBB.

Ordinary DS is first. DSi container work in PR #24 stays separate; ARM9i/ARM7i,
TWL services and extra hardware need their own execution work after DS.
