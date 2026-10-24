/* Original CC0 DS execution fixture. No game/SDK/BIOS code. */
.syntax unified
.cpu arm946e-s
.arm
.text
.global _start, main_end, thumb_start, thumb_end, loader, overlay1_source, overlay2_source
_start:
    mov r10, lr
    ldr r5, =0x02010000
    mov r0, #5
    str r0, [r5]
    mov r0, #1
    str r0, [r5, #4]
wait_arm7:
    ldr r1, [r5, #8]
    cmp r1, #0
    beq wait_arm7
    mov r0, r1
    ldr r4, =thumb_start + 1
    blx r4
    str r0, [r5, #12]
    mov r0, #0
    mov r1, #1
    bl loader
    ldr r4, =0x02020000
    ldr r0, [r5, #12]
    blx r4
    str r0, [r5, #16]
    mov r0, #0
    mov r1, #2
    bl loader
    ldr r0, [r5, #16]
    blx r4
    str r0, [r5, #20]
    ldr r1, [r5, #32]
    add r1, r1, #1
    str r1, [r5, #32]
    cmp r0, #32
    mov lr, r10
    bx lr
main_end:
.ltorg
.thumb
thumb_start:
    push {r1, lr}
    adds r0, #3
    pop {r1, pc}
thumb_end:
.balign 4
.arm
/* Original implementation copies the same overlay bytes as the native binding.
   It lets the whole fixture also execute independently in an ARM CPU oracle. */
loader:
    push {r2, r3, r12, lr}
    cmp r1, #1
    ldreq r2, =overlay1_source
    ldrne r2, =overlay2_source
    ldr r3, =0x02020000
    ldmia r2, {r12, lr}
    stmia r3, {r12, lr}
    mov r12, #0
    str r12, [r3, #8]
    str r12, [r3, #12]
    str r12, [r3, #16]
    str r12, [r3, #20]
    mov r0, #1
    pop {r2, r3, r12, pc}
.ltorg
overlay1_source:
    .word 0xe2800007, 0xe12fff1e
overlay2_source:
    .word 0xe280000b, 0xe12fff1e
