/* Original CC0 DS execution fixture. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main_end
_start:
    ldr r4, =0x02010000
wait_arm9:
    ldr r1, [r4, #4]
    cmp r1, #1
    bne wait_arm9
    ldr r0, [r4]
    add r0, r0, r0
    add r0, r0, #1
    str r0, [r4, #8]
    bx lr
main_end:
.ltorg
