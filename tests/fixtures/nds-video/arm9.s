/* Original CC0. Submit an oversized green 3D quad once per VBlank. */
.syntax unified
.cpu arm946e-s
.arm
.text
.global _start, main_end
_start:
    ldr r0, =0x04000304
    ldr r1, =0x020f
    strh r1, [r0]
    ldr r0, =0x04000000
    ldr r1, =0x00010108
    str r1, [r0]
    /* The secondary LCD remains a legible white 2D screen. */
    ldr r0, =0x04001000
    mov r1, #0x80
    str r1, [r0]
    ldr r0, =0x04000580
    ldr r1, =0xbfff0000
    str r1, [r0]
    ldr r0, =0x04000350
    ldr r1, =0x001f7c00
    str r1, [r0]
    ldr r1, =0x7fff
    str r1, [r0, #4]
    /* Identity projection and position matrices. */
    ldr r0, =0x04000440
    mov r1, #0
    str r1, [r0]
    str r1, [r0, #20]
    mov r1, #1
    str r1, [r0]
    str r1, [r0, #20]
wait_visible:
    ldr r0, =0x04000006
    ldrh r1, [r0]
    cmp r1, #192
    bcs wait_visible
wait_vblank:
    ldrh r1, [r0]
    cmp r1, #192
    bcc wait_vblank
    ldr r0, =0x040004a4
    ldr r1, =0x001f00c0
    str r1, [r0]
    ldr r0, =0x04000480
    ldr r1, =0x03e0
    str r1, [r0]
    ldr r0, =0x04000500
    mov r1, #1
    str r1, [r0]
    ldr r0, =0x0400048c
    mov r2, #0
    ldr r1, =0xd000d000
    str r1, [r0]
    str r2, [r0]
    ldr r1, =0xd0003000
    str r1, [r0]
    str r2, [r0]
    ldr r1, =0x30003000
    str r1, [r0]
    str r2, [r0]
    ldr r1, =0x3000d000
    str r1, [r0]
    str r2, [r0]
    ldr r0, =0x04000504
    str r2, [r0]
    ldr r0, =0x04000540
    str r2, [r0]
    b wait_visible
main_end:
.ltorg
