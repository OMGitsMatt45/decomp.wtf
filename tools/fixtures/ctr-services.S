/* CC0 original ARM11 program: allocation, events, srv IPC, config and ExeFS. */
.syntax unified
.arch armv6k
.arm
.section .text
.global _start

.macro send header, handle
    ldr r7, =\header
    str r7, [r6]
    mov r0, \handle
    svc 0x32
    cmp r0, #0
    bne failure
    ldr r0, [r6, #4]
    cmp r0, #0
    bne failure
.endm

.macro service first, second, length
    ldr r7, =\first
    str r7, [r6, #4]
    ldr r7, =\second
    str r7, [r6, #8]
    mov r7, #\length
    str r7, [r6, #12]
    mov r7, #0
    str r7, [r6, #16]
    send 0x00050100, r10
.endm

_start:
    mov r8, #0
    mov r0, #3
    mov r1, #0
    mov r2, #0
    mov r3, #0x1000
    mov r4, #3
    svc 0x01
    cmp r0, #0
    bne failure
    mov r5, r1
    mov r7, #0x5a
    str r7, [r5]
    ldr r0, [r5]
    cmp r0, #0x5a
    bne failure
    orr r8, r8, #1

    mov r1, #0
    svc 0x17
    cmp r0, #0
    bne failure
    mov r9, r1
    mov r0, r9
    svc 0x18
    mov r0, r9
    mov r2, #0
    mov r3, #0
    svc 0x24
    cmp r0, #0
    bne failure
    orr r8, r8, #2

    mrc p15, 0, r6, c13, c0, 3
    add r6, r6, #0x80
    ldr r1, =srv_name
    svc 0x2d
    cmp r0, #0
    bne failure
    mov r10, r1
    mov r7, #0x20
    str r7, [r6, #4]
    mov r7, #0
    str r7, [r6, #8]
    send 0x00010002, r10
    orr r8, r8, #4

    service 0x3a676663, 0x75, 5  /* cfg:u */
    ldr r11, [r6, #12]
    send 0x00050000, r11        /* GetSystemModel: Old3DS = 0 */
    ldr r0, [r6, #8]
    cmp r0, #0
    bne failure
    orr r8, r8, #8

    service 0x553a7366, 0x00524553, 7 /* fs:USER */
    ldr r11, [r6, #12]
    send 0x08010002, r11
    mov r7, #0
    str r7, [r6, #4]          /* transaction */
    mov r7, #3
    str r7, [r6, #8]          /* SelfNCCH archive */
    mov r7, #1
    str r7, [r6, #12]         /* empty archive path */
    str r7, [r6, #16]
    str r7, [r6, #28]         /* read-only open */
    mov r7, #2
    str r7, [r6, #20]         /* binary file path */
    mov r7, #4
    str r7, [r6, #24]
    mov r7, #0
    str r7, [r6, #32]
    ldr r7, =0x4002
    str r7, [r6, #36]
    ldr r7, =empty_path
    str r7, [r6, #40]
    ldr r7, =0x10002
    str r7, [r6, #44]
    ldr r7, =code_path
    str r7, [r6, #48]
    send 0x08030204, r11
    ldr r9, [r6, #12]

    mov r7, #0
    str r7, [r6, #4]
    str r7, [r6, #8]
    mov r7, #4
    str r7, [r6, #12]
    mov r7, #0x4c
    str r7, [r6, #16]
    str r5, [r6, #20]
    send 0x080200c2, r9
    ldr r0, [r6, #8]
    cmp r0, #4
    bne failure
    ldr r0, [r5]
    ldr r7, =0xe3a08000      /* first instruction, read through ExeFS */
    cmp r0, r7
    bne failure
    orr r8, r8, #16

    mov r0, r8
    svc 0x03
failure:
    ldr r0, =0xbad
    svc 0x03
.align 2
srv_name: .asciz "srv:"
empty_path: .byte 0
.align 2
code_path: .word 1
.ltorg
