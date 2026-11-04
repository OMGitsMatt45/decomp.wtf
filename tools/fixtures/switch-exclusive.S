// Original MIT AArch64 128-bit exclusive-load/store fixture.
.text
.global _entry
_entry:
    mov x9, #0x2000
    movk x9, #0x800, lsl #16
    mov x0, #0x11
    mov x1, #0x22
    stp x0, x1, [x9]
    ldxp x2, x3, [x9]
    add x2, x2, #1
    add x3, x3, #1
    stxp w4, x2, x3, [x9]
    ldaxp x5, x6, [x9]
    add x5, x5, #1
    add x6, x6, #1
    stlxp w7, x5, x6, [x9]
    ret
