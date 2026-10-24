"""Original CC0 MIPS-I inputs for the PS1 native candidate assessment.

These are CPU probes, with interrupts/timing disabled. They contain no BIOS,
SDK or retail bytes and do not stand in for a game/runtime compatibility test.
"""
import struct

BASE=0x80010000
RETURN=0x801fff00


def program():
    words=[];entries={}
    def function(name,body):
        while len(words)%4:words.append(0)
        entries[name]=BASE+len(words)*4;words.extend(body)
    # addiu v0,a0,7; jr ra; addiu v0,v0,5
    function('return_delay',[0x24820007,0x03e00008,0x24420005])
    # Signed comparison, a taken/untaken BEQ, and both return delay slots.
    function('signed_branch',[0x0085102a,0x10400004,0x24030001,0x24630004,
        0x03e00008,0x24420008,0x03e00008,0x24420010])
    # Preserve RA, call a helper, modify its argument in the call delay slot.
    function('call',[0x03e08021,0,0x24840003,0x0200f821,0x03e00008,0x24420001])
    function('helper',[0x00041040,0x03e00008,0x24420002])
    call=(entries['call']-BASE)//4
    words[call+1]=0x0c000000|((entries['helper']>>2)&0x03ffffff)
    # Main-RAM store/load with an explicit load-delay NOP, then XOR in JR's slot.
    function('memory',[0x3c088002,0xad040000,0x8d020000,0,0x03e00008,0x00451026])
    body=struct.pack('<'+'I'*len(words),*words)
    header=bytearray(2048);header[:8]=b'PS-X EXE'
    struct.pack_into('<I',header,0x10,BASE)
    struct.pack_into('<II',header,0x18,BASE,len(body))
    struct.pack_into('<I',header,0x30,0x801ff000)
    return bytes(header)+body,entries


def cases():
    inputs=[(0,0),(7,9),(0xffffffff,1),(0x80000000,0x7fffffff),(0x7fffffff,0x80000000)]
    return [(name,a,b) for name in ('return_delay','signed_branch','call','memory') for a,b in inputs]


def reference(image,entry,a,b):
    """Execute the original MIPS bytes independently of the generated C."""
    import unicorn
    from unicorn import mips_const as mips
    cpu=unicorn.Uc(unicorn.UC_ARCH_MIPS,unicorn.UC_MODE_MIPS32|unicorn.UC_MODE_LITTLE_ENDIAN)
    cpu.mem_map(0,0x200000);cpu.mem_write(BASE&0x1fffffff,image[2048:])
    cpu.reg_write(mips.UC_MIPS_REG_A0,a);cpu.reg_write(mips.UC_MIPS_REG_A1,b)
    cpu.reg_write(mips.UC_MIPS_REG_RA,RETURN)
    cpu.emu_start(entry,RETURN,count=1000)
    assert cpu.reg_read(mips.UC_MIPS_REG_PC)==RETURN,'original probe did not return'
    return dict(registers=[cpu.reg_read(mips.UC_MIPS_REG_0+i)&0xffffffff for i in range(32)],
        pc=cpu.reg_read(mips.UC_MIPS_REG_PC),memory=struct.unpack('<I',cpu.mem_read(0x20000,4))[0])
