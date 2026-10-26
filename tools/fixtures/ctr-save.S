/* CC0 original relocatable ARM11 save/relaunch qualification program. */
.syntax unified
.arch armv6k
.arm
.section .text
.global _start

.macro request header, handle
    ldr r7, =\header
    str r7, [r6]
    mov r0, \handle
    svc 0x32
    cmp r0, #0
    bne failure
.endm
.macro send header, handle
    request \header, \handle
    ldr r0, [r6, #4]
    cmp r0, #0
    bne failure
.endm

_start:
    mov r0, #3
    mov r1, #0
    mov r2, #0
    mov r3, #0x1000
    mov r4, #3
    svc 0x01
    cmp r0, #0
    bne failure
    mov r5, r1
    mrc p15, 0, r6, c13, c0, 3
    add r6, r6, #0x80
    adr r1, srv_name
    svc 0x2d
    cmp r0, #0
    bne failure
    mov r10, r1
    mov r7, #0x20
    str r7, [r6, #4]
    mov r7, #0
    str r7, [r6, #8]
    send 0x00010002, r10
    ldr r7, =0x553a7366
    str r7, [r6, #4]
    ldr r7, =0x00524553
    str r7, [r6, #8]
    mov r7, #7
    str r7, [r6, #12]
    mov r7, #0
    str r7, [r6, #16]
    send 0x00050100, r10
    ldr r11, [r6, #12]
    send 0x08010002, r11
    mov r4, #0
retry:
    bl open_save
    ldr r0, [r6, #4]
    cmp r0, #0
    beq opened
    /* Only the exact not-formatted result permits first-use formatting. */
    ldr r7, =0xc8a04554
    cmp r0, r7
    bne failure
    cmp r4, #0
    bne failure
    mov r4, #1
    mov r7, #32
    str r7, [r6, #4]
    mov r7, #1
    str r7, [r6, #8]
    str r7, [r6, #12]
    str r7, [r6, #16]
    str r7, [r6, #20]
    mov r7, #0
    str r7, [r6, #24]
    send 0x080f0180, r11
    b retry
opened:
    ldr r9, [r6, #12]
    mov r7, #0
    str r7, [r5]
    str r7, [r6, #4]
    str r7, [r6, #8]
    mov r7, #4
    str r7, [r6, #12]
    mov r7, #0x4c
    str r7, [r6, #16]
    str r5, [r6, #20]
    send 0x080200c2, r9
    ldr r0, [r6, #8]
    cmp r0, #0
    cmpne r0, #4
    bne failure
    ldr r8, [r5]
    adds r8, r8, #1
    bcs failure
    str r8, [r5]
    mov r7, #0
    str r7, [r6, #4]
    str r7, [r6, #8]
    mov r7, #4
    str r7, [r6, #12]
    mov r7, #1
    str r7, [r6, #16]
    mov r7, #0x4a
    str r7, [r6, #20]
    str r5, [r6, #24]
    send 0x08030102, r9
    ldr r0, [r6, #8]
    cmp r0, #4
    bne failure
    send 0x08080000, r9
    mov r1, r8
    mov r0, #0
    svc 0x03
failure:
    ldr r0, =0xbad
    svc 0x03

open_save:
    mov r7, #0
    str r7, [r6, #4]
    str r7, [r6, #32]
    mov r7, #4
    str r7, [r6, #8]
    mov r7, #1
    str r7, [r6, #12]
    str r7, [r6, #16]
    mov r7, #3
    str r7, [r6, #20]
    mov r7, #13
    str r7, [r6, #24]
    mov r7, #7
    str r7, [r6, #28]
    ldr r7, =0x4002
    str r7, [r6, #36]
    adr r7, empty_path
    str r7, [r6, #40]
    ldr r7, =0x34002
    str r7, [r6, #44]
    adr r7, file_path
    str r7, [r6, #48]
    request 0x08030204, r11
    bx lr
.align 2
srv_name: .asciz "srv:"
.align 2
empty_path: .byte 0
.align 2
file_path: .asciz "/counter.bin"
.ltorg
