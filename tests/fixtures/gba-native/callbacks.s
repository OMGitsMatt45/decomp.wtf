/* SPDX-License-Identifier: CC0-1.0. Original callbacks reached through RAM. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main, thumb_stack, thumb_leaf, arm_stack, arm_leaf, callback_table, ram_source, ram_end, interior, dual
_start:
    b main
.org 0xc0
main:
    ldr sp, =0x03007f00
    ldr r5, =0x02000000
    ldr r0, =callback_table
    str r0, [r5]
    mov r4, #0
next:
    ldr r1, [r5]
    ldr r1, [r1, r4, lsl #2]
    mov lr, pc
    bx r1
    add r2, r5, r4, lsl #2
    str r0, [r2, #4]
    add r4, r4, #1
    cmp r4, #4
    bne next
    ldr r0, =ram_source
    ldr r1, =0x03000000
    ldr r2, =copy_control
    swi 0x0b0000
    ldr r0, =0x03000000
    mov lr, pc
    bx r0
    str r0, [r5, #20]
    bl interior
    str r0, [r5, #24]
    ldr r3, =interior
    add r3, r3, #4
    str r3, [r5]
    ldr r3, [r5]
    mov r0, #3
    mov lr, pc
    bx r3
    str r0, [r5, #28]
    movs r0, #7
    bl dual
    str r0, [r5, #32]
    ldr r3, =dual
    add r3, r3, #1
    str r3, [r5]
    ldr r3, [r5]
    movs r0, #7
    mov lr, pc
    bx r3
    str r0, [r5, #36]
    push {r4-r8}
    ldr r0, =ram_source
    ldr r1, =0x03000100
    ldmia r0!, {r2-r8}
    stmia r1!, {r2-r8}
    pop {r4-r8}
    ldr r0, =0x03000100
    mov lr, pc
    bx r0
    str r0, [r5, #40]
    mov r8, #0
stack_copy:
    sub sp, sp, #64
    ldr r0, =stack_image
    mov r2, sp
    mov r3, #20
stack_copy_word:
    ldr r6, [r0], #4
    str r6, [r2], #4
    subs r3, r3, #4
    bne stack_copy_word
    mov r3, sp
    orr r3, r3, #1
    add r1, r8, #3
    mov lr, pc
    bx r3
    add r2, r5, r8, lsl #2
    str r0, [r2, #44]
    add r8, r8, #1
    cmp r8, #2
    bne stack_copy
    add sp, sp, #128
    ldr r0, =long_table
    str r0, [r5]
    mov r8, #0
long_callbacks:
    ldr r1, [r5]
    ldr r1, [r1, r8, lsl #2]
    mov lr, pc
    bx r1
    add r2, r5, r8, lsl #2
    str r0, [r2, #52]
    add r8, r8, #1
    cmp r8, #3
    bne long_callbacks
    ldr r0, =byte_helper
    ldr r0, [r0]
    sub sp, sp, #16
    str r0, [sp]
    mov r3, sp
    orr r3, r3, #1
    mov lr, pc
    bx r3
    add sp, sp, #16
    str r0, [r5, #64]
    ldr r0, =fragment_image
    ldr r1, =0x03000200
    ldr r2, =fragment_control
    bl bios_copy_wrapper
    ldr r0, =0x03000200
    mov lr, pc
    bx r0
    str r0, [r5, #72]
    ldr r1, =deferred_save
    orr r1, r1, #1
    str r1, [r5]
    ldr r1, [r5]
    mov r0, #0
    mov lr, pc
    bx r1
    str r0, [r5, #76]
    bl long_loop
    str r0, [r5, #80]
    ldr r0, =0x04000130
    ldrh r0, [r0]
    tst r0, #2
    bne idle
    ldr r0, =pc_dependent
    ldmia r0, {r0, r1}
    sub sp, sp, #32
    stmia sp, {r0, r1}
    add r2, r5, #68
    mov r3, sp
    mov lr, pc
    bx r3
    add sp, sp, #32
idle:
    b idle
    .ltorg
.thumb
.thumb_func
thumb_stack:
    push {lr}
    movs r0, #11
    pop {r3}
    bx r3
.thumb_func
thumb_leaf:
    movs r0, #22
    bx lr
.align 2
.arm
arm_stack:
    push {lr}
    mov r0, #33
    pop {pc}
arm_leaf:
    mov r0, #44
    bx lr
interior:
    mov r0, #11
    add r0, r0, #22
    bx lr
.thumb
.align 2
    nop
.thumb_func
thumb_prefix:
    nop
.arm
dual:
    /* ARM: condition MI is false, then BX LR. Thumb: MOVS 42; BX LR. */
    .word 0x4770202a, 0xe12fff1e
ram_source:
    push {r4, lr}
    ldr r4, =arm_leaf
    mov lr, pc
    bx r4
    add r0, r0, #11
    pop {r4, pc}
    .ltorg
ram_end:
.set copy_control, 0x04000000 + (ram_end - ram_source) / 4
.align 2
callback_table:
    .word thumb_stack, thumb_leaf, arm_stack, arm_leaf
    /* Pointer-shaped data: no return before the end of this image. */
    .word non_code + 1, 0x09fffffd, 0x080000c2, thumb_prefix, stack_image + 1
non_code:
    .space 16
.align 2
.thumb
stack_image:
    push {r4, lr}
    movs r4, #0
stack_loop:
    adds r4, #1
    cmp r4, r1
    bne stack_loop
    adds r0, r4, #7
    adds r0, #2
    pop {r4}
    pop {r3}
    bx r3
.align 2
long_table:
    .word long_one, long_two, long_three
.thumb_func
long_one:
    movs r0, #61
    .rept 8
    adds r0, #1
    .endr
    bx lr
.thumb_func
long_two:
    movs r0, #71
    .rept 8
    adds r0, #1
    .endr
    bx lr
.thumb_func
long_three:
    movs r0, #81
    .rept 8
    adds r0, #1
    .endr
    bx lr
.align 2
byte_helper:
    /* Its copy source is an even data pointer, not a Thumb function pointer. */
    movs r0, #42
    bx lr
.align 2
.arm
pc_dependent:
    str pc, [r2]
    bx lr
bios_copy_wrapper:
    swi 0x0b0000
    bx lr
long_loop:
    push {r4, lr}
    mov r4, #2
long_loop_again:
    mov r0, #0
    .rept 2300
    add r0, r0, #1
    .endr
    subs r4, r4, #1
    bne long_loop_again
    pop {r4, pc}
.align 2
fragment_image:
    ldr r2, fragment_keys
    ldrh r0, [r2]
    and r0, r0, #1
    add pc, pc, r0, lsl #2
    nop
    b fragment_zero
    b fragment_one
fragment_zero:
    mov r0, #66
    bx lr
fragment_one:
    mov r0, #77
    bx lr
fragment_keys:
    .word 0x04000130
fragment_end:
.set fragment_control, 0x04000000 + (fragment_end - fragment_image) / 4
.thumb
.align 2
deferred_save:
    cmp r0, #0
    beq deferred_push
    bx lr
deferred_push:
    push {r4, lr}
    movs r0, #90
    .rept 7
    adds r0, #1
    .endr
    pop {r4}
    pop {r3}
    bx r3
