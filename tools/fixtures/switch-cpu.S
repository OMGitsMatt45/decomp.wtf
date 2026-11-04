// Original AArch64 CPU fixture, MIT, written for decomp.wtf. No game code.
.text
.global _entry
_entry:
    b _start
    .space 0xfc
_start:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    mov x0, #5
    bl factorial
    adr x2, results
    str x0, [x2]
    mov w3, #-1
    adds w4, w3, #1
    cset x5, cs
    str w4, [x2, #8]
    str w5, [x2, #12]
    fmov s0, #1.5
    fmov s1, #2.0
    fadd s2, s0, s1
    str s2, [x2, #16]
    movi v3.4s, #7
    movi v4.4s, #9
    add v5.4s, v3.4s, v4.4s
    str q5, [x2, #32]
    adr x6, extra
    blr x6
    ldp x29, x30, [sp], #16
    ret
factorial:
    mov x1, #1
1:  mul x1, x1, x0
    subs x0, x0, #1
    b.ne 1b
    mov x0, x1
    ret
extra:
    add x0, x0, #30
    ret
.section .rodata
    .asciz "Original Switch CPU fixture"
.data
results:
    .zero 64
