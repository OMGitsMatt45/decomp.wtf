/* Original CC0. ARM9 stays idle while ARM7 reads the RTC. */
.syntax unified
.cpu arm946e-s
.arm
.text
.global _start, main_end
_start:
    b _start
main_end:
