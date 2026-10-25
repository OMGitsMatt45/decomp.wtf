/* Original CC0 GBA program. No game code, SDK, logo or BIOS. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main, thumb_code, irq, ram_source, ram_end, short_source
_start:
    b main
.org 0xc0
main:
    ldr r6, =0x02000000
    /* Raw SRAM counter persists across process restarts. */
    ldr r4, =0x0e000000
    ldrb r0, [r4]
    str r0, [r6]
    add r0, r0, #1
    and r0, r0, #255
    strb r0, [r4]
    str r0, [r6, #4]
    /* ARM BIOS Div: 100 / 7 = 14 remainder 2. */
    mov r0, #100
    mov r1, #7
    swi 0x060000
    str r0, [r6, #8]
    str r1, [r6, #12]
    adr lr, after_thumb
    ldr r0, =thumb_code + 1
    bx r0
after_thumb:
    str r0, [r6, #16]
    /* Copy a callable ARM routine to IWRAM. The native table validates its bytes. */
    ldr r0, =ram_source
    ldr r1, =0x03000000
    ldmia r0, {r2,r3}
    /* Holding B changes the copied opcode to exercise stale-native-code guards. */
    ldr r5, =0x04000130
    ldrh r5, [r5]
    tst r5, #2
    eoreq r2, r2, #1
    stmia r1, {r2,r3}
    adr lr, after_ram
    bx r1
after_ram:
    str r0, [r6, #28]
    /* A four-byte Thumb leaf lives beside changing RAM data, as in stack thunks. */
    mov r0, #90
    str r0, [r6, #32]
    ldr r1, =short_source
    bic r1, r1, #1
    ldr r2, [r1]
    ldr r1, =0x03000040
    str r2, [r1]
    ldr r2, =0x13579bdf
    str r2, [r1, #4]
    add r0, r6, #32
    add r1, r1, #1
    adr lr, after_leaf
    bx r1
after_leaf:
    str r0, [r6, #32]
    /* UP exercises temporal overlays: the same RAM address holds two routines,
       then two overlapping destinations hold the same longer Thumb routine. */
    ldr r0, =0x04000130
    ldrh r0, [r0]
    tst r0, #0x40
    bne after_overlays
    ldr r0, =overlay_a
    ldr r1, =0x03000080
    ldmia r0, {r2-r5,r7-r10}
    stmia r1, {r2-r5,r7-r10}
    adr lr, overlay_first_return
    bx r1
overlay_first_return:
    str r0, [r6, #40]
    ldr r0, =overlay_b
    ldr r1, =0x03000080
    ldmia r0, {r2-r5,r7-r10}
    stmia r1, {r2-r5,r7-r10}
    adr lr, overlay_second_return
    bx r1
overlay_second_return:
    str r0, [r6, #44]
    ldr r0, =overlay_thumb
    bic r0, r0, #1
    ldr r1, =0x03000100
    ldmia r0, {r2-r5,r7-r10}
    stmia r1, {r2-r5,r7-r10}
    mov r0, #1
    add r1, r1, #1
    adr lr, overlay_third_return
    bx r1
overlay_third_return:
    str r0, [r6, #48]
    ldr r0, =overlay_thumb
    bic r0, r0, #1
    ldr r1, =0x0300010c
    ldmia r0, {r2-r5,r7-r10}
    stmia r1, {r2-r5,r7-r10}
    mov r0, #2
    add r1, r1, #1
    adr lr, overlay_fourth_return
    bx r1
overlay_fourth_return:
    str r0, [r6, #52]
after_overlays:
    /* A running timer must observe straight-line instruction cycles before a branch. */
    ldr r5, =0x04000100
    mov r0, #0
    strh r0, [r5]
    mov r0, #0x80
    strh r0, [r5, #2]
    .rept 16
    add r7, r7, #1
    .endr
    ldrh r0, [r5]
    str r0, [r6, #36]
    mov r0, #0
    strh r0, [r5, #2]
    /* DMA3 fills the mode-3 picture red. */
    ldr r4, =0x02000100
    ldr r0, =0x001f001f
    str r0, [r4]
    ldr r5, =0x040000d4
    str r4, [r5]
    mov r0, #0x06000000
    str r0, [r5, #4]
    ldr r0, =0x85004b00
    str r0, [r5, #8]
    ldr r4, =0x04000000
    ldr r0, =0x0403
    strh r0, [r4]
    /* Square-wave channel 1 at full volume. */
    mov r0, #0x80
    strh r0, [r4, #0x84]
    ldr r0, =0x1177
    strh r0, [r4, #0x80]
    mov r0, #2
    strh r0, [r4, #0x82]
    ldr r0, =0xf080
    strh r0, [r4, #0x62]
    ldr r0, =0x8400
    strh r0, [r4, #0x64]
    /* VBlank handler and BIOS IntrWait flag. */
    ldr r0, =irq
    ldr r1, =0x03007ffc
    str r0, [r1]
    mov r0, #8
    strh r0, [r4, #4]
    ldr r1, =0x04000200
    mov r0, #1
    strh r0, [r1]
    strh r0, [r1, #8]
frame:
    ldr r1, =0x04000130
    ldrh r0, [r1]
    str r0, [r6, #20]
    swi 0x050000
    b frame
.ltorg
.thumb
.thumb_func
thumb_code:
    movs r0, #21
    lsls r0, r0, #1
    bx lr
.align 2
.arm
irq:
    ldr r0, =0x02000018
    ldr r1, [r0]
    add r1, r1, #1
    str r1, [r0]
    ldr r0, =0x04000202
    mov r1, #1
    strh r1, [r0]
    ldr r0, =0x03007ff8
    strh r1, [r0]
    bx lr
.ltorg
.thumb
.thumb_func
short_source:
    ldrb r0, [r0]
    bx lr
.align 2
.arm
ram_source:
    mov r0, #77
    bx lr
ram_end:
    .space 32
.align 2
overlay_a:
    mov r0, #91
    bx lr
    .space 24
overlay_b:
    mov r0, #92
    bx lr
    .space 24
.thumb
.thumb_func
overlay_thumb:
    push {r4, lr}
    movs r4, #7
overlay_loop:
    adds r0, #1
    subs r4, #1
    bne overlay_loop
    pop {r4}
    pop {r1}
    bx r1
    .space 16
