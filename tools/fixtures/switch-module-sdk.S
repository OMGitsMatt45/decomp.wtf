// Original MIT fixture library. No Nintendo SDK code.
.text
.global _entry, fixture_add, sdk_init
_entry:
    b fixture_add
    .word 0x80
    .org 0x80
    .ascii "MOD0"
    .word 0x1000-0x80
    .word 0x2010-0x80, 0x2110-0x80, 0, 0, 0
    .org 0x100
fixture_add:
    adr x8, counter_ptr
    ldr x8, [x8]
    ldr x9, [x8]
    add x0, x0, x9
    ret
sdk_init:
    adr x8, counter_ptr
    ldr x8, [x8]
    mov x9, #7
    str x9, [x8]
    ret
.section .rodata
    .space 0x800
.data
.global counter_ptr, sdk_array
counter_ptr: .quad 0
sdk_array: .quad 0
