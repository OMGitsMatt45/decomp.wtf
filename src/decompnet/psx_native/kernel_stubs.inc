/* Native callback bridges in the pinned BIOS's declared 16-byte install slots.
 * Four complete ABI shapes are supported: LUI/ADDIU into v0 or t0, followed
 * by JR or JALR and a NOP delay slot. Other bytes remain unhandled.
 * The pinned OpenBIOS exception vector has a separate exact k0 trampoline.
 * Dependency masks match the pinned emitter's instruction sequences.
 */
uint64_t decomp_kernel_stub_dispatches=0;
static int decomp_psx_kernel_stub(CPUState *cpu,uint32_t address,
                                const PsxKernelPatchRange *slots,uint32_t count){
    uint32_t physical=address&0x1fffffffu;
    if((address&3u)||physical>0x1ffff0u)return 0;
    int allowed=physical==0x80u;
    for(uint32_t i=0;i<count;i++)
        if(slots[i].hi-slots[i].lo==16u&&physical==slots[i].lo){allowed=1;break;}
    if(!allowed)return 0;
    const char *force=getenv("PSX_FORCE_INTERP");
    if(force&&*force&&*force!='0')return 0;
    uint32_t w0=cpu->read_word(physical),w1=cpu->read_word(physical+4u);
    uint32_t w2=cpu->read_word(physical+8u),w3=cpu->read_word(physical+12u);
    uint32_t reg,mask;int call;
    if(physical==0x80u){
        /* OpenBIOS fabe498f: the RAM vector installed by exception_init.
         * Its target is the already-compiled kernel exception entry. Do not
         * accept other instructions, targets, registers or link behavior. */
        if(w0!=0x3c1a0000u||w1!=0x275a27acu||w2!=0x03400008u||w3!=0u)return 0;
        reg=26;mask=0x04000000u;call=0;
    }else if((w0&0xffff0000u)==0x3c020000u&&(w1&0xffff0000u)==0x24420000u&&
       (w2==0x00400008u||w2==0x0040f809u)&&w3==0u){
        reg=2;mask=4u;call=w2==0x0040f809u;
    }else if((w0&0xffff0000u)==0x3c080000u&&(w1&0xffff0000u)==0x25080000u&&
             (w2==0x01000008u||w2==0x0100f809u)&&w3==0u){
        reg=8;mask=0x100u;call=w2==0x0100f809u;
    }else return 0;
    uint32_t high=(w0&0xffffu)<<16;
    uint32_t target=high+(uint32_t)(int32_t)(int16_t)(w1&0xffffu);
    if(target&3u)return 0;
#ifdef PSX_ENABLE_BLOCK_CYCLES
    psx_cyc_bb_defer_begin();
    psx_icache_fetch(cpu,address);psx_cyc_step(cpu,mask);
#endif
    cpu->gpr[reg]=high;
#ifdef PSX_ENABLE_BLOCK_CYCLES
    psx_icache_fetch(cpu,address+4u);psx_cyc_step(cpu,mask);
#endif
    cpu->gpr[reg]=target;
#ifdef PSX_ENABLE_BLOCK_CYCLES
    psx_icache_fetch(cpu,address+8u);
    psx_cyc_step(cpu,call?(mask|0x80000000u):(mask|1u));
#endif
    if(call)cpu->gpr[31]=address+16u;
#ifdef PSX_ENABLE_BLOCK_CYCLES
    psx_icache_fetch(cpu,address+12u);psx_cyc_step(cpu,1u);
    psx_cyc_bb_defer_flush();
#endif
    decomp_kernel_stub_dispatches++;
    psx_check_interrupts_at(cpu,target);
    cpu->pc=target;return 1;
}
