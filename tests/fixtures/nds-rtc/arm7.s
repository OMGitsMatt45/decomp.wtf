/* Original CC0. Read the DS RTC through its serial GPIO interface. */
.syntax unified
.cpu arm7tdmi
.arm
.text
.global _start, main_end
_start:
    ldr r0, =0x04000138
    ldr r1, =0x02010000
    mov r2, #0x72
    strb r2, [r0]
    mov r2, #0x76
    strb r2, [r0]
    mov r3, #0xa6
    mov r4, #8
send:
    and r2, r3, #1
    orr r2, r2, #0x74
    strb r2, [r0]
    orr r2, r2, #2
    strb r2, [r0]
    lsr r3, r3, #1
    subs r4, r4, #1
    bne send
    mov r5, #7
byte:
    mov r3, #0
    mov r4, #0
bit:
    mov r2, #0x64
    strb r2, [r0]
    ldrb r2, [r0]
    and r2, r2, #1
    orr r3, r3, r2, lsl r4
    mov r2, #0x66
    strb r2, [r0]
    add r4, r4, #1
    cmp r4, #8
    bne bit
    str r3, [r1], #4
    subs r5, r5, #1
    bne byte
    mov r2, #0x62
    strb r2, [r0]
idle:
    b idle
main_end:
    .ltorg
