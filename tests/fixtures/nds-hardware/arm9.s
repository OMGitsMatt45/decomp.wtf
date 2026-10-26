/* Original CC0 DS hardware fixture. No game, SDK, BIOS or mobile code. */
.syntax unified
.cpu arm946e-s
.arm
.text
.global _start, main_end, save_read, save_read_end, save_write, save_write_end, irq_start, irq_end, thumb_start, thumb_end
.global shared_start, shared_end, shared_exit, shared_exit_end, regular_start, regular_end, child_start, child_end
.global large_start, large_end
_start:
    ldr r6, =0x02010000
    bl save_read
    str r0, [r6, #12]
    add r0, r0, #1
    and r0, r0, #255
    bl save_write
    bl save_read
    str r0, [r6, #16]
    /* Read one 512-byte cartridge block using repeated one-word DMA. */
    ldr r4, =0x040000d4
    ldr r0, =0x04100010
    str r0, [r4]
    ldr r0, =0x02011000
    str r0, [r4, #4]
    ldr r0, =0xaf000001
    str r0, [r4, #8]
    ldr r4, =0x040001a0
    mov r0, #0xc000
    strh r0, [r4]
    ldr r0, =0x800000b7
    str r0, [r4, #8]
    mov r0, #0
    str r0, [r4, #12]
    ldr r0, =0xa1000010
    str r0, [r4, #4]
wait_card:
    ldr r0, [r4, #4]
    tst r0, #0x80000000
    bne wait_card
    ldr r4, =0x040000de
    mov r0, #0
    strh r0, [r4]
    ldr r4, =0x02011000
    ldr r0, [r4]
    str r0, [r6, #28]
    ldr r0, [r4, #508]
    str r0, [r6, #32]
    ldr r4, =0x04000214
    ldr r0, [r4]
    and r0, r0, #0x80000
    str r0, [r6, #36]
    /* DTCM stays enabled when ITCM is disabled (CP15 bits 16 and 18). */
    mrc p15, 0, r4, c1, c0, 0
    bic r0, r4, #0x40000
    orr r0, r0, #0x10000
    mcr p15, 0, r0, c1, c0, 0
    ldr r0, =0x00800010
    ldr r1, =0xa55a1234
    str r1, [r0]
    ldr r1, [r0]
    str r1, [r6, #24]
    mcr p15, 0, r4, c1, c0, 0
    ldr r4, =thumb_start + 1
    mov r0, #1
    blx r4
    str r0, [r6, #40]
    mov r0, #2
    blx r4
    str r0, [r6, #44]
    mvn r0, #0
    blx r4
    str r0, [r6, #48]
    ldr r4, =shared_start + 1
    mov r0, #1
    blx r4
    str r0, [r6, #52]
    ldr r4, =regular_start + 1
    blx r4
    str r0, [r6, #56]
    ldr r4, =large_start + 1
    ldr r0, =299
    blx r4
    str r0, [r6, #60]
    ldr r0, =300
    blx r4
    str r0, [r6, #64]
    /* Engine A: direct VRAM display, solid red. */
    ldr r0, =0x04000240
    mov r1, #0x80
    strb r1, [r0]
    ldr r0, =0x04000000
    mov r1, #0x20000
    str r1, [r0]
    ldr r0, =0x06800000
    ldr r1, =0x801f801f
    ldr r2, =24576
fill_top:
    str r1, [r0], #4
    subs r2, r2, #1
    bne fill_top
    /* Engine B: 256x256 direct-colour affine bitmap, solid green. */
    ldr r0, =0x04000242
    mov r1, #0x84
    strb r1, [r0]
    ldr r0, =0x04001000
    ldr r1, =0x10405
    str r1, [r0]
    ldr r1, =0x4084
    strh r1, [r0, #12]
    mov r1, #0x100
    strh r1, [r0, #32]
    strh r1, [r0, #38]
    ldr r0, =0x06200000
    ldr r1, =0x83e083e0
    ldr r2, =24576
fill_bottom:
    str r1, [r0], #4
    subs r2, r2, #1
    bne fill_bottom
    /* Cross-processor FIFO, not a host shortcut. */
    ldr r0, =0x04000184
    mov r1, #0x8000
    strh r1, [r0]
    ldr r1, =0x12345678
    str r1, [r0, #4]
    /* VBlank IRQ increments RAM through a generated guest handler. */
    ldr r0, =0x00803ffc
    ldr r1, =irq_start
    str r1, [r0]
    ldr r0, =0x04000004
    mov r1, #8
    strh r1, [r0]
    ldr r0, =0x04000210
    mov r1, #1
    str r1, [r0]
    str r1, [r0, #-8]
    mrs r0, cpsr
    bic r0, r0, #0x80
    msr cpsr_c, r0
    ldr r1, =0x04000130
poll:
    ldrh r0, [r1]
    str r0, [r6, #4]
    b poll
main_end:
.ltorg
save_read:
    push {r4, lr}
    ldr r4, =0x040001a0
    ldr r1, =0xa040
    strh r1, [r4]
    mov r0, #3
    strb r0, [r4, #2]
    mov r0, #0
    strb r0, [r4, #2]
    strb r0, [r4, #2]
    ldr r1, =0xa000
    strh r1, [r4]
    strb r0, [r4, #2]
    ldrb r0, [r4, #2]
    pop {r4, pc}
save_read_end:
.ltorg
save_write:
    push {r4, lr}
    mov r3, r0
    ldr r4, =0x040001a0
    ldr r1, =0xa000
    strh r1, [r4]
    mov r0, #6
    strb r0, [r4, #2]
    ldr r1, =0xa040
    strh r1, [r4]
    mov r0, #2
    strb r0, [r4, #2]
    mov r0, #0
    strb r0, [r4, #2]
    strb r0, [r4, #2]
    ldr r1, =0xa000
    strh r1, [r4]
    strb r3, [r4, #2]
    pop {r4, pc}
save_write_end:
.ltorg
irq_start:
    push {r0, r1, lr}
    ldr r0, =0x02010000
    ldr r1, [r0]
    add r1, r1, #1
    str r1, [r0]
    ldr r0, =0x04000214
    mov r1, #1
    str r1, [r0]
    pop {r0, r1, pc}
irq_end:
.ltorg
.thumb
thumb_start:
    cmp r0, #2
    bgt switch_default
    cmp r0, #0
    blt switch_default
    adds r1, r0, r0
    add r1, pc
    ldrh r1, [r1, #6]
    lsls r1, r1, #16
    asrs r1, r1, #16
switch_jump:
    add pc, r1
    .hword switch_zero - (switch_jump+4)
    .hword switch_one - (switch_jump+4)
    .hword switch_two - (switch_jump+4)
switch_zero:
    movs r0, #11
    bx lr
switch_one:
    movs r0, #22
    bx lr
switch_two:
    movs r0, #33
    bx lr
switch_default:
    movs r0, #255
    bx lr
thumb_end:
shared_start:
    push {r3, r4, r5, lr}
    sub sp, #12
    cmp r0, #0
    beq shared_inline_return
    movs r4, #42
    /* BL is a long jump to a shared return, not a returning subroutine. */
    bl shared_exit
    /* Pointer-like data after a nonreturning BL must not be decoded. */
    .word 0x02fff400
    movs r0, #99
    add sp, #12
    pop {r3, r4, r5, pc}
shared_inline_return:
    add sp, #12
    movs r0, #42
    str r0, [r6, #80]
    pop {r3, r4, r5, pc}
shared_end:
shared_exit:
    movs r0, r4
    add sp, #12
    pop {r3, r4, r5, pc}
shared_exit_end:
regular_start:
    push {r4, lr}
    bl child_start
    adds r0, #3
    pop {r4, pc}
regular_end:
child_start:
    push {r4, lr}
    movs r0, #60
    pop {r4, pc}
child_end:
large_start:
    movs r2, #150
    lsls r2, r2, #1
    cmp r0, r2
    blo large_dispatch
    b large_default
large_dispatch:
    adds r1, r0, r0
    add r1, pc
    ldrh r1, [r1, #6]
    lsls r1, r1, #16
    asrs r1, r1, #16
large_jump:
    add pc, r1
    .rept 299
    .hword large_default - (large_jump+4)
    .endr
    .hword large_last - (large_jump+4)
large_default:
    movs r0, #255
    bx lr
large_last:
    movs r0, #77
    bx lr
large_end:
