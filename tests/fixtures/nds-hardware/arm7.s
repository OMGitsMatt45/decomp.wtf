/* Original CC0. Receive an IPC word, start looping DS PCM8 audio, keep running. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main_end
_start:
    ldr r5, =0x02010000
    ldr r0, =0x04000184
    mov r1, #0x8000
    strh r1, [r0]
wait_fifo:
    ldrh r1, [r0]
    tst r1, #0x100
    bne wait_fifo
    ldr r0, =0x04100000
    ldr r1, [r0]
    str r1, [r5, #8]
    ldr r0, =samples
    ldr r1, =0x04000404
    str r0, [r1]
    ldr r0, =0xf000
    strh r0, [r1, #4]
    mov r0, #0
    strh r0, [r1, #6]
    mov r0, #4
    str r0, [r1, #8]
    ldr r1, =0x04000504
    mov r0, #0x200
    strh r0, [r1]
    ldr r0, =0x807f
    strh r0, [r1, #-4]
    ldr r1, =0x04000400
    ldr r0, =0x8840007f
    str r0, [r1]
keep_running:
    ldr r0, [r5, #20]
    add r0, r0, #1
    str r0, [r5, #20]
    b keep_running
main_end:
.ltorg
samples:
    .word 0x7f7f7f7f, 0x7f7f7f7f, 0x81818181, 0x81818181
