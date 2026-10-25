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
