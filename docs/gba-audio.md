# Optional enhanced GBA audio

The standalone GBA player can reconstruct DirectSound samples with a 16-tap
Blackman-windowed sinc before the hardware's final stereo mix. Original mode
retains the existing sample-and-hold path and reference PCM. Enhanced mode uses
the same game sequencer, instrument samples, DMA, timers, volume envelopes,
stereo routing and PSG channels. It reduces resampling images; it cannot recover
detail absent from the original samples or repair aliasing already introduced
by the game's software instrument mixer.

Desktop play defaults to enhanced mode. Headless/reference runs default to
original mode unless a saved preference or explicit option selects enhanced.
Use `--audio-mode original` or `--audio-mode enhanced` for a one-run override.
The option also selects PCM capture output, allowing repeatable comparisons.
PCM captures remain signed little-endian stereo 16-bit at 32768 Hz.

Open F1/Escape, or Start then R in a project with Start-menu integration. Select
the Audio category (left once from All) and press A/keyboard X to toggle Enhanced
Audio. Selection is saved in `<save path>.audio.cfg`, independently of the game
save and cheat choices. Turning all cheats off does not change audio settings.

The reconstruction uses previous samples plus upcoming samples already queued
in each hardware FIFO. It does not add an output queue, execute future game code,
or alter DMA/FIFO reads, guest registers, emulated cycles or game saves. If a
clock has stopped, history is insufficient, or the timer rate changes, playback
falls back to the current held sample until uniform history is available.
At source rates above the output rate, the kernel also limits the passband.

Interpolation history is presentation state. FIFO resets and state loads clear
it, without changing the save-state schema; startup warms up from held samples.
Reference checks compare original-mode PCM. Enhanced-mode checks compare game
execution, capture duration and independent analytic signals, plus real game
captures and frame pacing. Its PCM is intentionally different.

This is the first soundtrack enhancement. A replacement high-resolution MP2K
instrument mixer or optional soundtrack recordings would be separate features.
