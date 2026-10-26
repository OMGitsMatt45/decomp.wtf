/* SPDX-License-Identifier: CC0-1.0. Observe time at software-interrupt entry. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main, thumb_timer
_start:
    b main
.org 0xc0
main:
    ldr sp, =0x03007f00
    ldr r4, =0x04000100
    ldr r6, =0x02000000
    mov r0, #0
    strh r0, [r4, #2]
    strh r0, [r4]
    mov r0, #0x80
    strh r0, [r4, #2]
    swi 0
    str r0, [r6]
    adr lr, after_thumb
    ldr r0, =thumb_timer
    bx r0
after_thumb:
    movs r0, #0
    /* A false conditional SWI still costs its instruction cycle, but must
     * neither enter the handler nor increment its call count. */
    swine 0
    ldr r0, [r6, #12]
    str r0, [r6, #8]
idle:
    b idle
    .ltorg
.thumb
.thumb_func
thumb_timer:
    movs r0, #0
    strh r0, [r4, #2]
    strh r0, [r4]
    movs r0, #0x80
    strh r0, [r4, #2]
    swi 0
    str r0, [r6, #4]
    bx lr
