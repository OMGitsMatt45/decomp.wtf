# Original DS hardware fixture (CC0)

These original ARM9/ARM7 programs contain no game, SDK, BIOS or mobile data.
Their assembled bytes and symbol boundaries are recorded in `program.json`.
Regenerate with `uv run python tools/make_nds_static_fixture.py --fixture nds-hardware`.
Normal tests use the committed bytes and need no console compiler.

ARM9 renders a red top screen and green bottom screen, installs a generated
VBlank IRQ handler, reads keys, sends an IPC word and increments one EEPROM byte
through the cartridge SPI registers. ARM7 receives the FIFO word and drives a
looping original PCM8 waveform through the DS sound registers. Both CPUs keep
running. Tests inspect actual pixels, sound, IRQ/input state and save reload.

The guest also checks selective DTCM enable, repeated one-word cartridge DMA,
signed Thumb halfword switches, a 300-entry switch, and a BL to a shared return
epilogue. A normal nested BL with a separate saved frame must still resume its
caller. All paths have original assembled bytes and observable memory results.
