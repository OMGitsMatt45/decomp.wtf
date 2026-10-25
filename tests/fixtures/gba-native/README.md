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
