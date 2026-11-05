// Original MIT SDK-start ABI fixture, installed at sdk+0x180.
// No Nintendo SDK instructions are included. The exported symbol selects the
// startup ABI. The two host callbacks initialize shared_counter to 7 then 12.
.text
.global original_sdk_start
original_sdk_start:
    stp x19, x30, [sp, #-16]!
    mov x19, x3
    blr x2
    blr x19
    mov x0, #30
    bl fixture_add // sdk+0x100; the BL at sdk+0x194 is 0x97ffffdb
    ldp x19, x30, [sp], #16
    ret
