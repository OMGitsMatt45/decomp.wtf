// Original MIT fixture: relocations, constructors, cross-module calls and SVC/IPC.
.text
.global _entry, main_init, _start
_entry:
    b _start
    .word 0x80
    .org 0x80
    .ascii "MOD0"
    .word 0x1000-0x80
    .word 0x20a0-0x80, 0x21a0-0x80, 0, 0, 0
    .org 0x100
_start:
    stp x29, x30, [sp, #-16]!
    stp x19, x20, [sp, #-16]!
    stp x21, x22, [sp, #-16]!
    adr x19, results
    mov x0, #30
    adr x8, got_sdk
    ldr x8, [x8]
    blr x8
    str x0, [x19]

    mov x1, #0x200000
    svc #1
    str x1, [x19, #8]
    mov w1, #0xffff8000
    svc #0x25
    str x1, [x19, #16]
    svc #0x10

    adr x1, sm_name
    svc #0x1f
    mov x21, x1
    mrs x20, tpidrro_el0
.macro request source, dest
    adr x8, \source
    ldp x9, x10, [x8]
    stp x9, x10, [\dest]
    ldp x9, x10, [x8, #16]
    stp x9, x10, [\dest, #16]
    ldp x9, x10, [x8, #32]
    stp x9, x10, [\dest, #32]
    ldp x9, x10, [x8, #48]
    stp x9, x10, [\dest, #48]
.endm
    request ipc_initialize, x20
    mov x0, x21
    svc #0x21
    ldp w9, w10, [x20, #24]
    stp w9, w10, [x19, #24]
    request ipc_get_service, x20
    mov x0, x21
    svc #0x21
    ldr w22, [x20, #12]
    request ipc_language, x20
    mov x0, x22
    svc #0x21
    ldr x9, [x20, #32]
    str x9, [x19, #32]

    ldr x0, [x19, #8]
    request ipc_language, x0
    mov x1, #0x100
    mov x2, x22
    svc #0x22
    ldr x8, [x19, #8]
    ldr x9, [x8, #32]
    str x9, [x19, #72]
    mov x0, x22
    svc #0x16
    mov x0, x22
    svc #0x21
    str x0, [x19, #40]
    mov x0, x21
    svc #0x16

    adr x8, relative_result
    ldr x9, [x8]
    str x9, [x19, #48]
    adr x8, weak_slot
    ldr x9, [x8]
    str x9, [x19, #56]
    mov x1, #0x1000
    svc #1
    str x0, [x19, #64]
    svc #0x1e
    str x0, [x19, #80]
    adr x0, debug_message
    mov x1, #22
    svc #0x27
    ldr x0, [x19]
    ldp x21, x22, [sp], #16
    ldp x19, x20, [sp], #16
    ldp x29, x30, [sp], #16
    ret
main_init:
    adr x8, shared_counter
    ldr x9, [x8]
    add x9, x9, #5
    str x9, [x8]
    ret

.section .rodata
    .space 0x600
ipc_initialize:
    .long 4, 0x80000008
    .long 1
    .quad 0
    .zero 12
    .ascii "SFCI"
    .long 0, 0, 0x12345678
    .zero 16
ipc_get_service:
    .long 4, 8
    .quad 0
    .ascii "SFCI"
    .long 0, 1, 0x12345678
    .quad 0x746573
    .zero 24
ipc_language:
    .long 4, 8
    .quad 0
    .ascii "SFCI"
    .long 0, 0, 0x12345678
    .quad 0
    .zero 24
sm_name:
    .asciz "sm:"
debug_message:
    .ascii "Switch module runtime\n"

.data
.global shared_counter, results, got_sdk, relative_result, main_array, weak_slot
shared_counter: .quad 0
results: .zero 120
got_sdk: .quad 0
relative_result: .quad 0x2008
main_array: .quad 0
weak_slot: .quad 0
