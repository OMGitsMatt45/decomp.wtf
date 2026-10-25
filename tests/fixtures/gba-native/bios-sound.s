// SPDX-License-Identifier: CC0-1.0
// Original BIOS service/mixer qualification cartridge. No game/BIOS bytes.
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start
_start: b main
.org 0xc0
main:
    mov r7,#0x02000000
    ldr r5,=0x02001000
    mov r0,r5
    swi 0x1a0000
    ldr r0,[r5]
    str r0,[r7]
    ldr r0,=0x0093f180
    swi 0x1b0000
    ldr r0,[r5,#4]
    str r0,[r7,#4]
    ldr r0,[r5,#8]
    str r0,[r7,#8]
    ldr r0,[r5,#0x10]
    str r0,[r7,#12]
    ldr r0,[r5,#0x14]
    str r0,[r7,#16]
    ldr r0,=0x02003000
    swi 0x2a0000
    ldr r0,=wave
    mov r1,#60
    mov r2,#0
    swi 0x1f0000
    str r0,[r7,#20]
    // Install one looping fixed-rate channel with original square-wave PCM.
    add r4,r5,#0x50
    ldr r0,=0x607f0880
    str r0,[r4]
    ldr r0,=0xc880c8ff
    str r0,[r4,#4]
    ldr r0,=wave
    str r0,[r4,#0x24]
    mov r0,#8192
    str r0,[r4,#0x20]
    // Use a cartridge callback from SoundDriverMain as well as the IRQ callback.
    ldr r0,=music_callback
    str r0,[r5,#0x20]
    ldr r0,=irq
    ldr r1,=0x03007ffc
    str r0,[r1]
    mov r0,#0x04000000
    mov r1,#8
    strh r1,[r0,#4]
    add r0,r0,#0x200
    mov r1,#1
    strh r1,[r0]
    strh r1,[r0,#8]
    mov r6,#64
mix:
    swi 0x050000
    swi 0x1c0000
    subs r6,r6,#1
    bne mix
    // Capture mixer state before clearing the channel.
    ldr r0,[r4]
    str r0,[r7,#24]
    ldr r0,[r4,#8]
    str r0,[r7,#28]
    // Hash the active left/right mixer buffers before clearing the channel.
    add r0,r5,#0x350
    ldr r1,=0x811c9dc5
    ldr r2,=3168
    ldr r3,=0x01000193
    mov r8,#0
hash_active:
    ldrb r12,[r0],#1
    cmp r12,#0
    addne r8,r8,#1
    eor r1,r1,r12
    mul r12,r1,r3
    mov r1,r12
    subs r2,r2,#1
    bne hash_active
    str r8,[r7,#0x48]
    str r1,[r7,#0x4c]
    swi 0x1e0000
    ldr r0,[r4]
    str r0,[r7,#32]
    mov r6,#16
silence:
    swi 0x050000
    swi 0x1c0000
    subs r6,r6,#1
    bne silence
    // The full buffer has had more than one DMA period to become silent.
    add r0,r5,#0x350
    ldr r2,=3168
    mov r1,#0
check_silence:
    ldrb r12,[r0],#1
    orr r1,r1,r12
    subs r2,r2,#1
    bne check_silence
    str r1,[r7,#0x50]
    swi 0x280000
    ldr r0,=0x040000c6
    ldrh r1,[r0]
    str r1,[r7,#36]
    // A Thumb caller exercises the BIOS's Thumb exception decoding/return.
    adr lr,returned
    ldr r0,=thumb_on+1
    bx r0
returned:
    ldr r0,=0x040000c6
    ldrh r1,[r0]
    str r1,[r7,#40]
    mov r0,#1
    str r0,[r7,#44]
forever: b forever
.ltorg
irq:
    push {r4,lr}
    swi 0x1d0000
    ldr r4,=0x04000202
    mov r0,#1
    strh r0,[r4]
    ldr r4,=0x03007ff8
    ldrh r1,[r4]
    orr r1,r1,#1
    strh r1,[r4]
    ldr r4,=0x02000040
    ldr r0,[r4]
    add r0,r0,#1
    str r0,[r4]
    pop {r4,lr}
    bx lr
music_callback:
    ldr r0,=0x02000044
    ldr r1,[r0]
    add r1,r1,#1
    str r1,[r0]
    bx lr
.ltorg
.thumb
.thumb_func
thumb_on:
    swi 0x29
    bx lr
.align 2
wave:
    .hword 0,0x4000
    .word 0x00800000,0,64
    .rept 16
    .byte 96
    .endr
    .rept 16
    .byte -96
    .endr
    .rept 16
    .byte 48
    .endr
    .rept 16
    .byte -48
    .endr
