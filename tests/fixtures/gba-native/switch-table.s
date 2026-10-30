/* SPDX-License-Identifier: CC0-1.0. Original bounded Thumb dispatch after a join. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main, thumb_switch, case_zero, case_one, case_two, cases
_start:
    b main
.org 0xc0
main:
    ldr sp, =0x03007f00
    ldr r5, =0x02000000
    ldr r7, =thumb_switch
    mov r6, #0
next:
    mov r0, r6
    mov lr, pc
    bx r7
    str r0, [r5, r6, lsl #2]
    add r6, r6, #1
    cmp r6, #5
    bne next
idle:
    b idle
    .ltorg
.thumb
.thumb_func
thumb_switch:
    push {r4, lr}
    cmp r0, #3
    bne dispatch
    movs r0, #1
dispatch:
    /* The first linear path knows 1, but incoming branches also supply 0/2/4.
     * The bounded index must retain all three table cases, not just case one. */
    cmp r0, #2
    bhi fallback
    lsls r0, r0, #2
    ldr r1, =cases
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
    .ltorg
.align 2
cases:
    .word case_zero, case_one, case_two
    /* These are internal labels, deliberately even and without Thumb tags.
     * Their non-leaf bodies have no stack-save prologue of their own. */
.align 2
    nop
case_zero:
    ldr r4, =0x11223344
    movs r0, #4
    bl increment
    b done
case_one:
    ldr r4, =0x11223344
    movs r0, #8
    bl increment
    b done
case_two:
    ldr r4, =0x11223344
    movs r0, #12
    bl increment
    b done
fallback:
    movs r0, #17
done:
    pop {r4}
    pop {r3}
    bx r3
.thumb_func
increment:
    adds r0, #1
    bx lr
    .ltorg
