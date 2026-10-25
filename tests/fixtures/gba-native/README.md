# Original GBA native fixture

`program.s` and the generated `program.json` are original CC0 test content. No
commercial ROM, Nintendo logo, SDK library, BIOS or remake asset is included.
The Python wrapper supplies an original header with a valid checksum.

Rebuild the byte fixture with GNU ARM binutils:

```sh
python tools/make_gba_native_fixture.py --binutils /path/to/arm-none-eabi/bin
```

The program crosses ARM/Thumb, calls BIOS division, copies code to IWRAM, fills
a mode-3 picture through DMA, starts a square wave, services VBlank IRQs, polls
buttons, and increments a real SRAM cartridge counter. Holding B changes the
copied opcode; the runtime must reject stale native code and either interpret
the actual bytes or fail in strict mode.

A separate four-byte Thumb helper is copied beside changing RAM data. Feedback must
recover its bounded ROM-backed body without treating adjacent data as instructions.
The live Timer0 read after straight-line arithmetic checks that translated
instructions advance hardware time before the next branch.

Holding Up additionally replaces an ARM routine at one RAM address, then installs
one longer Thumb routine at two overlapping destinations. Coverage must retain both
ARM versions and recover all four calls in strict static mode. Independently
reviewed profiles exercise the same overlapping views. A direct-entry guard also
rejects the wrong body even when another valid variant exists at that address.

`timer_micro()` in `../gba_native.py` builds three original ARM programs with zero,
one and sixteen additions between timer enable and its read. Independent mGBA
0.10.5 runs produce 7, 13 and 103 ticks. Both native and reference execution must
match these observations. Peripheral tests cover all timer prescalers, cascading,
overflow/reload, interrupt acknowledgement, RTC repeated GPIO writes, aborted
transfers, leap days and calendar rollovers. An original miniature 16 KiB firmware
fixture checks optional BIOS exception entry/return in ARM and Thumb states.

CI uses short temporary roots to keep Visual Studio's compiler-probe tracking logs
within MSBuild's path limit. Exported fixture folders still contain spaces.

`bios-sound.s` and `bios-sound.json` are a separate original CC0 cartridge. They
contain no BIOS image or commercial samples. The cartridge exercises BIOS sound
initialization, mode selection, MIDI frequency calculation, jump-table creation,
VSync, mixing, channel clearing and VSync off/on, including a Thumb caller and
native IRQ/music callbacks. Its original waveform covers fixed-rate looping,
resampled looping and one-shot channels. Mixer-buffer checksums are compared with
independent mGBA; native/reference PCM must match and become silent after clearing.

The optional execution tests require your own 16 KiB BIOS. From the repository root:

```sh
# Install the pinned source SDK once using the normal toolchain command.
uv run --locked --group dev --python 3.12 decomp toolchain install anygba-sdk
DECOMP_GBA_TEST_BIOS='/path/to/gba_bios.bin' uv run --locked --group dev --python 3.12 python -m pytest -q tests/test_gba_native.py -k optional_owner_bios_sound
```

In PowerShell, set `$env:DECOMP_GBA_TEST_BIOS = 'C:\path\gba_bios.bin'` and run the
same `uv run ...` command. CMake and a host C/C++ compiler are required. The tests
build an independent export and keep the supplied BIOS outside its source tree.
CI skips these three cases when no BIOS is supplied; it still runs the original
miniature-firmware checks. Regeneration accepts `--fixture bios-sound` to rebuild
only this cartridge, or `--fixture all` (the default) for both assembly fixtures.
