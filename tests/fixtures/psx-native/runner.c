/* SPDX-License-Identifier: CC0-1.0. Original CPU-only qualification host.
 * Memory is a bounded test array. No IRQ, peripheral or cycle model is supplied.
 * The complete PS1 hardware runtime still needs its own integration/qualification.
 */
#include "cpu_state.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char memory[0x200000],original[0x10000];
static size_t original_size;
static unsigned calls;
int g_psx_cps_mode;
volatile uint32_t g_psx_last_fn_entry;
uint32_t g_debug_last_store_pc;

static unsigned physical(uint32_t address,size_t size) {
    const uint32_t p=address&0x1fffffffu;
    if(p>=sizeof(memory)||size>sizeof(memory)-p)abort();
    return p;
}
uint8_t psx_read_byte(uint32_t address){return memory[physical(address,1)];}
uint16_t psx_read_half(uint32_t address){const unsigned p=physical(address,2);return memory[p]|((uint16_t)memory[p+1]<<8);}
uint32_t psx_read_word(uint32_t address){const unsigned p=physical(address,4);return memory[p]|((uint32_t)memory[p+1]<<8)|((uint32_t)memory[p+2]<<16)|((uint32_t)memory[p+3]<<24);}
void psx_write_byte(uint32_t address,uint8_t value){memory[physical(address,1)]=value;}
void psx_write_half(uint32_t address,uint16_t value){const unsigned p=physical(address,2);memory[p]=(uint8_t)value;memory[p+1]=(uint8_t)(value>>8);}
void psx_write_word(uint32_t address,uint32_t value){const unsigned p=physical(address,4);for(unsigned i=0;i<4;++i)memory[p+i]=(uint8_t)(value>>(i*8));}

/* IRQs and accelerated BIOS calls are absent in these CPU probes. */
void psx_check_interrupts_at(CPUState* cpu,uint32_t resume){(void)cpu;if(resume&3)abort();}
void psx_check_interrupts_dispatch_entry(CPUState* cpu,uint32_t resume){psx_check_interrupts_at(cpu,resume);++calls;}
int psx_vsync_query_hle_try(CPUState* cpu,uint32_t address){(void)cpu;(void)address;return 0;}

/* Supply the dispatcher's immutable-byte guard for this bounded test image.
 * This tests native dispatch/rejection; it does not qualify dirty_ram.c itself.
 */
int dirty_ram_text_native_ok_ranges(const uint32_t* ranges,uint32_t count) {
    for(uint32_t i=0;i<count;++i) {
        const uint32_t address=ranges[i*2]&0x1fffffffu,size=ranges[i*2+1];
        if(address<0x10000||address-0x10000>original_size||size>original_size-(address-0x10000))return 0;
        if(memcmp(memory+address,original+address-0x10000,size)!=0)return 0;
    }
    return count!=0;
}
int dirty_ram_text_native_ok_ranges_from(const uint32_t* ranges,uint32_t count,uint32_t pc){(void)pc;return dirty_ram_text_native_ok_ranges(ranges,count);}
extern int psx_dispatch_game_compiled(CPUState*,uint32_t);

int main(int argc,char** argv) {
    if(argc!=5&&argc!=6)return 1;
    FILE* file=fopen(argv[1],"rb");if(!file)return 2;
    if(fseek(file,2048,SEEK_SET)!=0)return 2;
    original_size=fread(original,1,sizeof(original),file);fclose(file);
    if(!original_size||original_size==sizeof(original))return 2;
    memcpy(memory+0x10000,original,original_size);
    CPUState cpu={0};cpu.pc=(uint32_t)strtoul(argv[2],NULL,0);
    cpu.gpr[4]=(uint32_t)strtoul(argv[3],NULL,0);cpu.gpr[5]=(uint32_t)strtoul(argv[4],NULL,0);
    cpu.gpr[31]=0x801fff00u;cpu.read_word=psx_read_word;cpu.write_word=psx_write_word;
    cpu.read_half=psx_read_half;cpu.write_half=psx_write_half;cpu.read_byte=psx_read_byte;cpu.write_byte=psx_write_byte;
    if(argc==6)memory[physical(cpu.pc,1)]^=1;
    for(unsigned step=0;cpu.pc!=0x801fff00u;++step) {
        if(step>=1000)return 3;
        if(!psx_dispatch_game_compiled(&cpu,cpu.pc)) {
            if(argc==6){puts("{\"native_rejected\":true}");return 0;}
            fprintf(stderr,"probe would require fallback at %08x\n",cpu.pc);return 4;
        }
    }
    if(argc==6)return 5;
    printf("{\"registers\":[");
    for(unsigned i=0;i<32;++i)printf("%s%u",i?",":"",cpu.gpr[i]);
    printf("],\"pc\":%u,\"memory\":%u,\"native_dispatches\":%u,\"cps_mode\":%d}\n",cpu.pc,psx_read_word(0x80020000u),calls,g_psx_cps_mode);
    return calls==0||g_psx_cps_mode!=1;
}
